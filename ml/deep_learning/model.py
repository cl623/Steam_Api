"""LSTM-based classification model for Steam Market price prediction (V3.0 Phase 2).

Architecture
------------
1. **LSTM encoder** – processes the temporal sequence ``(batch, seq_len, F_temporal)``
   through one or more LSTM layers.  The final hidden state captures the
   "regime" the market is in (velocity of price/volume changes, event proximity).

2. **Static fusion** – the LSTM's last-timestep output is concatenated with
   the per-item static feature vector ``(batch, F_static)`` (item type,
   condition, StatTrak flag, etc.).

3. **Classification head** – two fully-connected layers with dropout,
   producing logits over ``NUM_BUCKETS`` return-probability classes.
   Softmax is applied during inference; during training the raw logits are
   passed to ``CrossEntropyLoss``.

The model also exposes a ``predict_proba`` helper that returns calibrated
bucket probabilities and the predicted bucket index.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from .buckets import NUM_BUCKETS, BUCKET_NAMES
from .dataset import NUM_TEMPORAL_FEATURES, NUM_STATIC_FEATURES

logger = logging.getLogger(__name__)


class SteamMarketLSTM(nn.Module):
    """Multi-layer LSTM with static-feature fusion and softmax bucket head.

    Parameters
    ----------
    temporal_features : int
        Number of per-timestep input features (default from Phase 1 pipeline).
    static_features : int
        Number of per-item static features.
    hidden_size : int
        LSTM hidden dimension.
    num_layers : int
        Number of stacked LSTM layers.
    dropout : float
        Dropout probability applied between LSTM layers and in the FC head.
    num_classes : int
        Number of output buckets.
    bidirectional : bool
        If True, use a bidirectional LSTM (doubles effective hidden size).
        Typically False for causal / time-series problems.
    """

    def __init__(
        self,
        temporal_features: int = NUM_TEMPORAL_FEATURES,
        static_features: int = NUM_STATIC_FEATURES,
        hidden_size: int = 128,
        num_layers: int = 2,
        dropout: float = 0.3,
        num_classes: int = NUM_BUCKETS,
        bidirectional: bool = False,
    ):
        super().__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.num_directions = 2 if bidirectional else 1

        # ── LSTM encoder ────────────────────────────────────────────────────
        self.lstm = nn.LSTM(
            input_size=temporal_features,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
            bidirectional=bidirectional,
        )

        lstm_out_size = hidden_size * self.num_directions

        # ── Static fusion + classification head ─────────────────────────────
        fused_size = lstm_out_size + static_features

        self.head = nn.Sequential(
            nn.Linear(fused_size, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, num_classes),
        )

        self._init_weights()

    def _init_weights(self):
        for name, param in self.lstm.named_parameters():
            if "weight_ih" in name:
                nn.init.xavier_uniform_(param)
            elif "weight_hh" in name:
                nn.init.orthogonal_(param)
            elif "bias" in name:
                nn.init.zeros_(param)
        for m in self.head.modules():
            if isinstance(m, nn.Linear):
                nn.init.kaiming_normal_(m.weight, nonlinearity="relu")
                nn.init.zeros_(m.bias)

    def forward(
        self,
        sequence: torch.Tensor,
        static: torch.Tensor,
    ) -> torch.Tensor:
        """Forward pass.

        Parameters
        ----------
        sequence : Tensor (batch, seq_len, temporal_features)
        static   : Tensor (batch, static_features)

        Returns
        -------
        logits : Tensor (batch, num_classes)
        """
        # LSTM: use the output at the last timestep
        lstm_out, (h_n, _) = self.lstm(sequence)
        # h_n shape: (num_layers * num_directions, batch, hidden_size)
        # Take the final layer's hidden state(s)
        if self.num_directions == 2:
            last_hidden = torch.cat(
                [h_n[-2], h_n[-1]], dim=-1
            )  # (batch, hidden_size*2)
        else:
            last_hidden = h_n[-1]  # (batch, hidden_size)

        # Fuse with static features
        fused = torch.cat([last_hidden, static], dim=-1)

        logits = self.head(fused)
        return logits

    # ── convenience methods ─────────────────────────────────────────────────

    @torch.no_grad()
    def predict_proba(
        self,
        sequence: torch.Tensor,
        static: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """Return softmax probabilities and predicted bucket indices.

        Returns
        -------
        probs   : Tensor (batch, num_classes)
        preds   : LongTensor (batch,)
        """
        self.eval()
        logits = self.forward(sequence, static)
        probs = F.softmax(logits, dim=-1)
        preds = probs.argmax(dim=-1)
        return probs, preds

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)

    def summary(self) -> str:
        lines = [
            f"SteamMarketLSTM",
            f"  LSTM: {NUM_TEMPORAL_FEATURES} -> {self.hidden_size} "
            f"x {self.num_layers} layers "
            f"({'bidirectional' if self.num_directions == 2 else 'unidirectional'})",
            f"  Static features: {NUM_STATIC_FEATURES}",
            f"  Classification head: -> {NUM_BUCKETS} buckets",
            f"  Trainable parameters: {self.count_parameters():,}",
        ]
        return "\n".join(lines)


# ── save / load ─────────────────────────────────────────────────────────────

def save_checkpoint(
    model: SteamMarketLSTM,
    optimizer: Optional[torch.optim.Optimizer],
    epoch: int,
    metrics: Dict,
    path: str | Path,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "model_state_dict": model.state_dict(),
        "epoch": epoch,
        "metrics": metrics,
        "model_config": {
            "hidden_size": model.hidden_size,
            "num_layers": model.num_layers,
            "bidirectional": model.num_directions == 2,
        },
    }
    if optimizer is not None:
        state["optimizer_state_dict"] = optimizer.state_dict()
    torch.save(state, path)
    logger.info("Checkpoint saved -> %s  (epoch %d)", path, epoch)


def load_checkpoint(
    path: str | Path,
    device: torch.device | str = "cpu",
) -> Tuple[SteamMarketLSTM, Dict]:
    """Load a saved checkpoint and reconstruct the model."""
    state = torch.load(path, map_location=device, weights_only=False)
    cfg = state.get("model_config", {})
    model = SteamMarketLSTM(
        hidden_size=cfg.get("hidden_size", 128),
        num_layers=cfg.get("num_layers", 2),
        bidirectional=cfg.get("bidirectional", False),
    )
    model.load_state_dict(state["model_state_dict"])
    model.to(device)
    logger.info("Model loaded from %s (epoch %d)", path, state.get("epoch", -1))
    return model, state
