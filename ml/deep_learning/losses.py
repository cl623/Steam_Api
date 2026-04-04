"""Custom loss functions for V3.0 Phase 3.

Two loss families are provided:

1. **Classification losses** (for the bucket approach from Phase 2):
   - ``compute_class_weights`` -- inverse-frequency weighting with an
     optional multiplier that further boosts the "Massive Spike" bucket.
   - ``FocalLoss`` -- focal loss that down-weights easy/confident examples
     and up-weights hard ones, combined with per-class weights.

2. **Regression loss** (for the continuous log-return path):
   - ``AsymmetricMSELoss`` -- penalises under-prediction of positive
     returns more heavily than over-prediction, forcing the model to pay
     attention to the fat right tail of the market.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from .buckets import NUM_BUCKETS, BUCKET_NAMES, log_returns_to_labels


# ── class weight computation ────────────────────────────────────────────────

def compute_class_weights(
    targets: Sequence[float],
    spike_boost: float = 2.0,
    normalize: bool = True,
) -> torch.FloatTensor:
    """Compute per-class weights from a set of log-return targets.

    The base weight for each class is the *inverse frequency* relative to the
    largest class::

        w_i = max_count / count_i

    An additional ``spike_boost`` multiplier is applied to the last bucket
    ("Massive Spike") so the model is penalised even more heavily for
    missing profitable opportunities.

    Parameters
    ----------
    targets : sequence of float
        Log-return values from the training set.
    spike_boost : float
        Extra multiplier for the Massive Spike bucket (default 2.0).
        Set to 1.0 to disable the boost.
    normalize : bool
        If True, scale the weights so they sum to ``NUM_BUCKETS``
        (i.e. average weight = 1.0).  This keeps the loss magnitude
        comparable across different weighting schemes.

    Returns
    -------
    weights : FloatTensor of shape ``(NUM_BUCKETS,)``
    """
    labels = log_returns_to_labels(targets)
    counts = np.bincount(labels, minlength=NUM_BUCKETS).astype(float)
    counts = np.maximum(counts, 1.0)

    max_count = counts.max()
    weights = max_count / counts

    # Boost the Massive Spike bucket (last one)
    weights[-1] *= spike_boost

    if normalize:
        weights = weights * (NUM_BUCKETS / weights.sum())

    return torch.tensor(weights, dtype=torch.float32)


# ── focal loss ──────────────────────────────────────────────────────────────

class FocalLoss(nn.Module):
    """Focal loss for multi-class classification.

    Focal loss reduces the contribution of easy (high-confidence) examples
    and focuses training on hard, misclassified samples.  Combined with
    per-class weights it is a powerful tool for imbalanced classification.

    .. math::

        FL(p_t) = -\\alpha_t \\, (1 - p_t)^\\gamma \\, \\log(p_t)

    Parameters
    ----------
    weight : Tensor (num_classes,) or None
        Per-class weights (e.g. from ``compute_class_weights``).
    gamma : float
        Focusing parameter.  gamma=0 is equivalent to weighted CE.
        gamma=2 is a common default.
    reduction : str
        ``"mean"`` (default) or ``"sum"`` or ``"none"``.
    """

    def __init__(
        self,
        weight: torch.Tensor | None = None,
        gamma: float = 2.0,
        reduction: str = "mean",
    ):
        super().__init__()
        self.gamma = gamma
        self.reduction = reduction
        if weight is not None:
            self.register_buffer("weight", weight)
        else:
            self.weight = None

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        """
        Parameters
        ----------
        logits  : (batch, num_classes)
        targets : (batch,) LongTensor of class indices
        """
        log_probs = F.log_softmax(logits, dim=-1)
        probs = log_probs.exp()

        # Gather the log-prob and prob of the true class for each sample
        targets_1d = targets.unsqueeze(1)
        log_pt = log_probs.gather(1, targets_1d).squeeze(1)
        pt = probs.gather(1, targets_1d).squeeze(1)

        focal_factor = (1.0 - pt) ** self.gamma
        loss = -focal_factor * log_pt

        # Apply per-class weight
        if self.weight is not None:
            w = self.weight.to(logits.device)
            class_w = w[targets]
            loss = loss * class_w

        if self.reduction == "mean":
            return loss.mean()
        if self.reduction == "sum":
            return loss.sum()
        return loss


# ── asymmetric regression loss ──────────────────────────────────────────────

class AsymmetricMSELoss(nn.Module):
    """Asymmetric MSE that penalises under-prediction of positive returns.

    For samples where the true return is positive and the model
    under-predicts (predicted < actual), the squared error is multiplied
    by ``upside_penalty``.  This directly addresses the tree-model tendency
    (now inherited by the LSTM regression path) to "play it safe" and
    compress predictions toward the mean.

    For all other error directions the standard MSE applies.

    Parameters
    ----------
    upside_penalty : float
        Multiplier applied to the squared error when the model under-predicts
        a positive return.  Default 3.0.
    reduction : str
        ``"mean"`` (default) or ``"sum"`` or ``"none"``.
    """

    def __init__(self, upside_penalty: float = 3.0, reduction: str = "mean"):
        super().__init__()
        self.upside_penalty = upside_penalty
        self.reduction = reduction

    def forward(
        self,
        predicted: torch.Tensor,
        actual: torch.Tensor,
    ) -> torch.Tensor:
        """
        Parameters
        ----------
        predicted : (batch,) predicted log-returns
        actual    : (batch,) true log-returns
        """
        error = predicted - actual
        sq_error = error ** 2

        # Condition: true return is positive AND model under-predicted
        missed_upside = (actual > 0) & (predicted < actual)
        penalty = torch.where(
            missed_upside,
            torch.tensor(self.upside_penalty, device=sq_error.device),
            torch.tensor(1.0, device=sq_error.device),
        )
        weighted = sq_error * penalty

        if self.reduction == "mean":
            return weighted.mean()
        if self.reduction == "sum":
            return weighted.sum()
        return weighted
