#!/usr/bin/env python
"""Train Embedding + LSTM on weak sentiment labels."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import f1_score
from torch.utils.data import DataLoader, TensorDataset

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from nlp.dataset import (  # noqa: E402
    add_weak_labels,
    apply_label_source,
    default_db_path,
    load_comments_dataframe,
    split_meta_dict,
    train_val_test_split,
)
from nlp.models_lstm import (  # noqa: E402
    CommentLSTM,
    build_vocab,
    encode_texts,
    save_lstm_bundle,
)

logger = logging.getLogger("train_sentiment_lstm")


def run_epoch(model, loader, opt, device, train: bool) -> float:
    if train:
        model.train()
    else:
        model.eval()
    total_loss = 0.0
    n = 0
    crit = nn.CrossEntropyLoss()
    for xb, yb in loader:
        xb = xb.to(device)
        yb = yb.to(device)
        if train:
            opt.zero_grad()
        logits = model(xb)
        loss = crit(logits, yb)
        if train:
            loss.backward()
            opt.step()
        total_loss += float(loss.item()) * len(xb)
        n += len(xb)
    return total_loss / max(n, 1)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--split-mode", choices=("random", "by_match", "by_time"), default="by_match")
    ap.add_argument("--val-fraction", type=float, default=0.15)
    ap.add_argument("--test-fraction", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--max-len", type=int, default=64)
    ap.add_argument("--embed-dim", type=int, default=128)
    ap.add_argument("--hidden-dim", type=int, default=128)
    ap.add_argument("--patience", type=int, default=4)
    ap.add_argument(
        "--save-dir",
        type=Path,
        default=PROJECT_ROOT / "sentiment_models" / "lstm",
    )
    ap.add_argument(
        "--label-source",
        choices=("weak", "gold", "hybrid"),
        default="weak",
    )
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    db_path = args.db or default_db_path()
    if not db_path.is_file():
        logger.error("Database not found: %s", db_path)
        return 1

    raw = load_comments_dataframe(db_path, limit=args.limit)
    if raw.empty:
        logger.error("No comments in DB.")
        return 1
    df = add_weak_labels(raw)
    tr, va, te = train_val_test_split(
        df,
        mode=args.split_mode,
        val_fraction=args.val_fraction,
        test_fraction=args.test_fraction,
        random_state=args.seed,
    )
    tr_f = apply_label_source(tr, args.label_source)
    if tr_f.empty:
        logger.error("Train split empty after label-source filter.")
        return 1

    texts_tr = tr_f["raw_text"].astype(str).tolist()
    stoi, _ = build_vocab(texts_tr)
    vocab_size = len(stoi)

    def enc(series):
        return encode_texts(series.astype(str).tolist(), stoi, args.max_len)

    x_tr = torch.tensor(enc(tr_f["raw_text"]), dtype=torch.long)
    y_tr = torch.tensor(tr_f["label"].to_numpy(), dtype=torch.long)
    train_loader = DataLoader(
        TensorDataset(x_tr, y_tr), batch_size=args.batch_size, shuffle=True
    )

    va_loader = None
    va_f = apply_label_source(va, args.label_source)
    if not va_f.empty:
        x_va = torch.tensor(enc(va_f["raw_text"]), dtype=torch.long)
        y_va = torch.tensor(va_f["label"].to_numpy(), dtype=torch.long)
        va_loader = DataLoader(
            TensorDataset(x_va, y_va), batch_size=args.batch_size, shuffle=False
        )

    model = CommentLSTM(
        vocab_size=vocab_size,
        embed_dim=args.embed_dim,
        hidden_dim=args.hidden_dim,
        num_classes=3,
        padding_idx=0,
    ).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)

    best_val = float("inf")
    best_state = None
    bad = 0
    for ep in range(1, args.epochs + 1):
        tr_loss = run_epoch(model, train_loader, opt, device, True)
        if va_loader is not None:
            va_loss = run_epoch(model, va_loader, opt, device, False)
            logger.info("epoch %s train_loss=%.4f val_loss=%.4f", ep, tr_loss, va_loss)
            if va_loss < best_val:
                best_val = va_loss
                best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                bad = 0
            else:
                bad += 1
                if bad >= args.patience:
                    logger.info("early stop at epoch %s", ep)
                    break
        else:
            logger.info("epoch %s train_loss=%.4f", ep, tr_loss)
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    if best_state is not None:
        model.load_state_dict(best_state)

    args.save_dir.mkdir(parents=True, exist_ok=True)
    bundle = args.save_dir / "lstm_weak.pt"
    save_lstm_bundle(bundle, model.cpu(), stoi, args.max_len)

    def eval_tensor(x_np, y_np):
        if len(y_np) == 0:
            return {"n": 0, "f1_macro": 0.0}
        model.eval()
        model.to(device)
        loader = DataLoader(
            TensorDataset(
                torch.tensor(x_np, dtype=torch.long),
                torch.tensor(y_np, dtype=torch.long),
            ),
            batch_size=args.batch_size,
            shuffle=False,
        )
        preds = []
        with torch.no_grad():
            for xb, _ in loader:
                logits = model(xb.to(device))
                preds.append(torch.argmax(logits, dim=1).cpu().numpy())
        p = np.concatenate(preds)
        return {
            "n": int(len(y_np)),
            "f1_macro": float(f1_score(y_np, p, average="macro", zero_division=0)),
            "f1_micro": float(f1_score(y_np, p, average="micro", zero_division=0)),
        }

    te_f = apply_label_source(te, args.label_source)
    x_te = enc(te_f["raw_text"]) if not te_f.empty else np.zeros((0, args.max_len), dtype=np.int64)
    y_te = te_f["label"].to_numpy() if not te_f.empty else np.zeros(0, dtype=np.int64)
    metrics = {
        "test": eval_tensor(x_te, y_te),
        "split": split_meta_dict(
            args.split_mode,
            args.val_fraction,
            args.test_fraction,
            args.seed,
            len(tr),
            len(va),
            len(te),
        ),
        "max_len": args.max_len,
        "vocab_size": vocab_size,
        "label_source": args.label_source,
    }
    (args.save_dir / "lstm_metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    logger.info("Saved %s", bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
