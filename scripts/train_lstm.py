#!/usr/bin/env python
"""Train the V3.0 LSTM bucket-classification model.

Usage::

    # Quick training run (50 items, 10 epochs) -- unweighted CE baseline
    python scripts/train_lstm.py --max-items 50 --epochs 10

    # Phase 3: weighted cross-entropy (auto-computed from training data)
    python scripts/train_lstm.py --max-items 50 --epochs 15 --loss weighted-ce

    # Phase 3: focal loss (gamma=2, class-weighted, spike boost)
    python scripts/train_lstm.py --max-items 50 --epochs 15 --loss focal --spike-boost 2.5

    # Full training with event window
    python scripts/train_lstm.py --use-event-window --epochs 30 --loss weighted-ce

    # Item holdout (generalization to unseen market_hash_name values)
    python scripts/train_lstm.py --max-items 50 --split-mode item_holdout --holdout-fraction 0.2

    # Custom hyperparameters
    python scripts/train_lstm.py --hidden-size 256 --num-layers 3 --lr 0.0005

    # Resume from checkpoint
    python scripts/train_lstm.py --resume models_lstm/best_model.pt --epochs 20
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import f1_score
from torch.optim.lr_scheduler import ReduceLROnPlateau

from ml.deep_learning.dataset import (
    build_dataloaders,
    NUM_TEMPORAL_FEATURES,
    NUM_STATIC_FEATURES,
)
from ml.deep_learning.model import SteamMarketLSTM, save_checkpoint, load_checkpoint
from ml.deep_learning.buckets import (
    NUM_BUCKETS,
    BUCKET_NAMES,
    log_returns_to_labels,
    bucket_distribution,
)
from ml.deep_learning.losses import compute_class_weights, FocalLoss

logger = logging.getLogger("train_lstm")


# ── metrics helpers ─────────────────────────────────────────────────────────

def compute_metrics(
    all_preds: np.ndarray,
    all_labels: np.ndarray,
) -> dict:
    """Compute accuracy, per-class accuracy, and confusion matrix."""
    n = len(all_labels)
    correct = (all_preds == all_labels).sum()
    accuracy = correct / n if n > 0 else 0.0

    confusion = np.zeros((NUM_BUCKETS, NUM_BUCKETS), dtype=int)
    for pred, true in zip(all_preds, all_labels):
        confusion[true, pred] += 1

    per_class_acc = {}
    for i, name in enumerate(BUCKET_NAMES):
        total = (all_labels == i).sum()
        right = confusion[i, i]
        per_class_acc[name] = right / total if total > 0 else 0.0

    f1_macro = float(
        f1_score(all_labels, all_preds, average="macro", zero_division=0)
    )

    return {
        "accuracy": float(accuracy),
        "f1_macro": f1_macro,
        "per_class_accuracy": per_class_acc,
        "confusion_matrix": confusion,
        "n_samples": n,
    }


def print_confusion_matrix(confusion: np.ndarray) -> None:
    """Pretty-print the confusion matrix."""
    col_width = 14
    header = " " * 18 + "".join(f"{'Pred ' + str(i):>{col_width}}" for i in range(NUM_BUCKETS))
    logger.info(header)
    for i, name in enumerate(BUCKET_NAMES):
        row = f"  True {i} ({name[:8]:>8}) "
        row += "".join(f"{confusion[i, j]:>{col_width}}" for j in range(NUM_BUCKETS))
        logger.info(row)


# ── training loop ───────────────────────────────────────────────────────────

def train_one_epoch(
    model: SteamMarketLSTM,
    loader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> float:
    model.train()
    total_loss = 0.0
    n_batches = 0

    for batch in loader:
        seq = batch["sequence"].to(device)
        static = batch["static"].to(device)
        targets = batch["target"]
        labels = log_returns_to_labels(targets.numpy())
        labels = torch.from_numpy(labels).to(device)

        optimizer.zero_grad()
        logits = model(seq, static)
        loss = criterion(logits, labels)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()

        total_loss += loss.item()
        n_batches += 1

    return total_loss / max(n_batches, 1)


@torch.no_grad()
def evaluate(
    model: SteamMarketLSTM,
    loader,
    criterion: nn.Module,
    device: torch.device,
) -> dict:
    model.eval()
    total_loss = 0.0
    n_batches = 0
    all_preds = []
    all_labels = []

    for batch in loader:
        seq = batch["sequence"].to(device)
        static = batch["static"].to(device)
        targets = batch["target"]
        labels_np = log_returns_to_labels(targets.numpy())
        labels = torch.from_numpy(labels_np).to(device)

        logits = model(seq, static)
        loss = criterion(logits, labels)
        total_loss += loss.item()
        n_batches += 1

        preds = logits.argmax(dim=-1).cpu().numpy()
        all_preds.append(preds)
        all_labels.append(labels_np)

    all_preds = np.concatenate(all_preds)
    all_labels = np.concatenate(all_labels)
    avg_loss = total_loss / max(n_batches, 1)

    metrics = compute_metrics(all_preds, all_labels)
    metrics["loss"] = avg_loss
    return metrics


# ── main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Train V3.0 LSTM model")
    # Data
    parser.add_argument("--game-id", default="730")
    parser.add_argument("--max-items", type=int, default=None)
    parser.add_argument("--seq-len", type=int, default=30)
    parser.add_argument("--prediction-days", type=int, default=7)
    parser.add_argument("--use-event-window", action="store_true")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument(
        "--split-mode",
        choices=["pooled", "item_holdout"],
        default="pooled",
        help="pooled=chronological sample split (legacy); item_holdout=hold out whole items",
    )
    parser.add_argument(
        "--holdout-fraction",
        type=float,
        default=0.2,
        help="Fraction of items in test set when split_mode=item_holdout",
    )
    parser.add_argument(
        "--holdout-seed",
        type=int,
        default=42,
        help="RNG seed for selecting held-out items",
    )
    # Model
    parser.add_argument("--hidden-size", type=int, default=128)
    parser.add_argument("--num-layers", type=int, default=2)
    parser.add_argument("--dropout", type=float, default=0.3)
    parser.add_argument("--bidirectional", action="store_true")
    # Training
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--patience", type=int, default=5,
                        help="Early stopping patience (epochs without improvement)")
    # Loss
    parser.add_argument("--loss", choices=["ce", "weighted-ce", "focal"], default="ce",
                        help="Loss function: ce (baseline), weighted-ce, focal (Phase 3)")
    parser.add_argument("--spike-boost", type=float, default=2.0,
                        help="Extra weight multiplier for Massive Spike bucket (weighted-ce/focal)")
    parser.add_argument("--focal-gamma", type=float, default=2.0,
                        help="Focusing parameter for focal loss (higher = more focus on hard examples)")
    # I/O
    parser.add_argument("--save-dir", default="models_lstm")
    parser.add_argument("--resume", type=str, default=None,
                        help="Path to checkpoint to resume from")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("train_lstm.log", mode="a"),
        ],
    )

    db_path = PROJECT_ROOT / "data" / "market_data.db"
    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        sys.exit(1)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Device: %s", device)

    # ── data ────────────────────────────────────────────────────────────────
    logger.info("Loading data and building DataLoaders...")
    train_loader, test_loader, normalizer, split_meta = build_dataloaders(
        db_path,
        game_id=args.game_id,
        seq_len=args.seq_len,
        prediction_days=args.prediction_days,
        batch_size=args.batch_size,
        max_items=args.max_items,
        use_event_window=args.use_event_window,
        split_mode=args.split_mode,
        holdout_fraction=args.holdout_fraction,
        holdout_seed=args.holdout_seed,
    )
    logger.info("Split meta: %s", split_meta)

    # Log target distribution
    train_targets = [s["target"].item() for s in train_loader.dataset]
    test_targets = [s["target"].item() for s in test_loader.dataset]
    logger.info("Train target distribution: %s", bucket_distribution(train_targets))
    logger.info("Test  target distribution: %s", bucket_distribution(test_targets))

    # ── model ───────────────────────────────────────────────────────────────
    start_epoch = 0
    if args.resume:
        logger.info("Resuming from %s", args.resume)
        model, ckpt = load_checkpoint(args.resume, device=device)
        start_epoch = ckpt.get("epoch", 0)
    else:
        model = SteamMarketLSTM(
            temporal_features=NUM_TEMPORAL_FEATURES,
            static_features=NUM_STATIC_FEATURES,
            hidden_size=args.hidden_size,
            num_layers=args.num_layers,
            dropout=args.dropout,
            num_classes=NUM_BUCKETS,
            bidirectional=args.bidirectional,
        ).to(device)

    logger.info("\n%s", model.summary())

    # ── loss, optimizer, scheduler ──────────────────────────────────────────
    if args.loss in ("weighted-ce", "focal"):
        weights = compute_class_weights(
            train_targets, spike_boost=args.spike_boost,
        ).to(device)
        logger.info("Class weights (spike_boost=%.1f): %s",
                    args.spike_boost,
                    {n: f"{w:.3f}" for n, w in zip(BUCKET_NAMES, weights.tolist())})

    if args.loss == "ce":
        criterion = nn.CrossEntropyLoss()
        logger.info("Loss: CrossEntropyLoss (unweighted baseline)")
    elif args.loss == "weighted-ce":
        criterion = nn.CrossEntropyLoss(weight=weights)
        logger.info("Loss: CrossEntropyLoss (class-weighted)")
    elif args.loss == "focal":
        criterion = FocalLoss(weight=weights, gamma=args.focal_gamma)
        logger.info("Loss: FocalLoss (gamma=%.1f, class-weighted)", args.focal_gamma)

    optimizer = torch.optim.Adam(
        model.parameters(), lr=args.lr, weight_decay=args.weight_decay,
    )
    scheduler = ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=2,
    )

    # ── training loop ───────────────────────────────────────────────────────
    save_dir = Path(args.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    # Save normalizer alongside model
    normalizer.save(save_dir / "normalizer.npz")

    best_val_loss = float("inf")
    epochs_no_improve = 0

    logger.info("=" * 70)
    logger.info("Starting training  |  epochs=%d  lr=%.4f  patience=%d  loss=%s",
                args.epochs, args.lr, args.patience, args.loss)
    logger.info("=" * 70)

    for epoch in range(start_epoch, start_epoch + args.epochs):
        t0 = time.time()

        train_loss = train_one_epoch(model, train_loader, criterion, optimizer, device)
        val_metrics = evaluate(model, test_loader, criterion, device)
        val_loss = val_metrics["loss"]
        val_acc = val_metrics["accuracy"]
        val_f1 = val_metrics["f1_macro"]

        scheduler.step(val_loss)
        current_lr = optimizer.param_groups[0]["lr"]
        elapsed = time.time() - t0

        logger.info(
            "Epoch %3d/%d  |  train_loss=%.4f  val_loss=%.4f  val_acc=%.4f  "
            "val_f1_macro=%.4f  lr=%.6f  time=%.1fs",
            epoch + 1, start_epoch + args.epochs,
            train_loss, val_loss, val_acc, val_f1, current_lr, elapsed,
        )

        # Checkpoint best model
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            epochs_no_improve = 0
            save_checkpoint(
                model, optimizer, epoch + 1,
                {"val_loss": val_loss, "val_accuracy": val_acc, "val_f1_macro": val_f1},
                save_dir / "best_model.pt",
            )
        else:
            epochs_no_improve += 1

        # Early stopping
        if epochs_no_improve >= args.patience:
            logger.info("Early stopping triggered after %d epochs without improvement",
                        args.patience)
            break

    # ── final evaluation on best model ──────────────────────────────────────
    logger.info("")
    logger.info("=" * 70)
    logger.info("Final evaluation (best checkpoint)")
    logger.info("=" * 70)

    best_model, _ = load_checkpoint(save_dir / "best_model.pt", device=device)
    final_metrics = evaluate(best_model, test_loader, criterion, device)

    logger.info("  Test loss     : %.4f", final_metrics["loss"])
    logger.info("  Test accuracy : %.4f  (%d / %d)",
                final_metrics["accuracy"],
                int(final_metrics["accuracy"] * final_metrics["n_samples"]),
                final_metrics["n_samples"])
    logger.info("  Test F1 (macro): %.4f", final_metrics["f1_macro"])
    logger.info("")

    # Persist split metadata for comparison / lift scripts
    meta_out = {
        "split_mode": args.split_mode,
        "holdout_fraction": args.holdout_fraction,
        "holdout_seed": args.holdout_seed,
        "max_items": args.max_items,
        "seq_len": args.seq_len,
        "prediction_days": args.prediction_days,
        "use_event_window": args.use_event_window,
        "split_meta": split_meta,
    }
    with open(save_dir / "split_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta_out, f, indent=2)
    logger.info("Wrote %s", save_dir / "split_meta.json")
    logger.info("")
    logger.info("  Per-class accuracy:")
    for name, acc in final_metrics["per_class_accuracy"].items():
        logger.info("    %-20s  %.4f", name, acc)

    logger.info("")
    logger.info("  Confusion matrix:")
    print_confusion_matrix(final_metrics["confusion_matrix"])

    # Save the final epoch model as well
    save_checkpoint(
        model, optimizer, epoch + 1,
        {"val_loss": val_loss, "val_accuracy": val_acc},
        save_dir / "last_model.pt",
    )

    logger.info("")
    logger.info("Models saved to %s/", save_dir)
    logger.info("  best_model.pt   - lowest validation loss")
    logger.info("  last_model.pt   - final epoch")
    logger.info("  normalizer.npz  - fitted scaler (required for inference)")


if __name__ == "__main__":
    main()
