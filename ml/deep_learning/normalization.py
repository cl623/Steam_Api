"""Sequence-aware normalization for LSTM inputs.

LSTMs are highly sensitive to input scale.  This module provides a
``SequenceNormalizer`` that computes per-feature statistics across the
*flattened* training sequences and applies Min-Max or Standard scaling
consistently across train/test/inference data.

Usage::

    norm = SequenceNormalizer(method="minmax")  # or "standard"
    norm.fit(train_sequences)                   # list of (seq_len, F) arrays
    train_scaled = norm.transform(train_sequences)
    test_scaled  = norm.transform(test_sequences)

    # Persist for inference
    norm.save("models/normalizer.npz")
    norm = SequenceNormalizer.load("models/normalizer.npz")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Literal

import numpy as np

logger = logging.getLogger(__name__)


class SequenceNormalizer:
    """Per-feature scaling across a set of 2-D sequence arrays.

    Parameters
    ----------
    method : ``"minmax"`` | ``"standard"``
        ``"minmax"``  – scale each feature to [0, 1] using global min/max.
        ``"standard"``– zero-mean, unit-variance (like sklearn StandardScaler).
    clip : float or None
        After scaling, clip values to [-clip, clip].  Useful to bound outliers
        that sit beyond training-set extremes.  ``None`` disables clipping.
    """

    def __init__(
        self,
        method: Literal["minmax", "standard"] = "minmax",
        clip: float | None = 5.0,
    ):
        self.method = method
        self.clip = clip

        # Populated by .fit()
        self._min: np.ndarray | None = None
        self._max: np.ndarray | None = None
        self._mean: np.ndarray | None = None
        self._std: np.ndarray | None = None
        self._num_features: int | None = None

    @property
    def is_fitted(self) -> bool:
        if self.method == "minmax":
            return self._min is not None
        return self._mean is not None

    def fit(self, sequences: List[np.ndarray]) -> "SequenceNormalizer":
        """Compute statistics from a list of ``(seq_len, F)`` arrays."""
        stacked = np.concatenate(sequences, axis=0)  # (total_steps, F)
        self._num_features = stacked.shape[1]

        if self.method == "minmax":
            self._min = np.nanmin(stacked, axis=0)
            self._max = np.nanmax(stacked, axis=0)
            rng = self._max - self._min
            rng[rng == 0] = 1.0  # avoid division by zero for constant features
            self._max = self._min + rng  # store the safe max
            logger.info(
                "SequenceNormalizer fit (minmax): %d features, %d total timesteps",
                self._num_features, stacked.shape[0],
            )
        else:
            self._mean = np.nanmean(stacked, axis=0)
            self._std = np.nanstd(stacked, axis=0)
            self._std[self._std == 0] = 1.0
            logger.info(
                "SequenceNormalizer fit (standard): %d features, %d total timesteps",
                self._num_features, stacked.shape[0],
            )

        return self

    def transform(self, sequences: List[np.ndarray]) -> List[np.ndarray]:
        """Scale a list of ``(seq_len, F)`` arrays using fitted statistics."""
        if not self.is_fitted:
            raise RuntimeError("Call .fit() before .transform()")

        out = []
        for seq in sequences:
            scaled = self._scale_array(seq.astype(np.float32))
            out.append(scaled)
        return out

    def fit_transform(self, sequences: List[np.ndarray]) -> List[np.ndarray]:
        return self.fit(sequences).transform(sequences)

    def inverse_transform_column(
        self,
        values: np.ndarray,
        col_idx: int,
    ) -> np.ndarray:
        """Reverse scaling for a single feature column (useful for debugging)."""
        if self.method == "minmax":
            return values * (self._max[col_idx] - self._min[col_idx]) + self._min[col_idx]
        return values * self._std[col_idx] + self._mean[col_idx]

    # ── persistence ─────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"method": self.method, "clip": self.clip if self.clip else -1}
        if self.method == "minmax":
            data["min_"] = self._min
            data["max_"] = self._max
        else:
            data["mean_"] = self._mean
            data["std_"] = self._std
        np.savez(path, **data)
        logger.info("Normalizer saved to %s", path)

    @classmethod
    def load(cls, path: str | Path) -> "SequenceNormalizer":
        d = np.load(path, allow_pickle=True)
        method = str(d["method"])
        clip_val = float(d["clip"])
        norm = cls(method=method, clip=clip_val if clip_val >= 0 else None)
        if method == "minmax":
            norm._min = d["min_"]
            norm._max = d["max_"]
            norm._num_features = len(norm._min)
        else:
            norm._mean = d["mean_"]
            norm._std = d["std_"]
            norm._num_features = len(norm._mean)
        logger.info("Normalizer loaded from %s (%s, %d features)", path, method, norm._num_features)
        return norm

    # ── internals ───────────────────────────────────────────────────────────

    def _scale_array(self, arr: np.ndarray) -> np.ndarray:
        """Scale a single (seq_len, F) array."""
        arr = np.nan_to_num(arr, nan=0.0)
        if self.method == "minmax":
            scaled = (arr - self._min) / (self._max - self._min)
        else:
            scaled = (arr - self._mean) / self._std
        if self.clip is not None:
            scaled = np.clip(scaled, -self.clip, self.clip)
        return scaled
