# Version 2.5 Roadmap – Addressing Model Limitations

## Context

Version 2.2 delivered a return-based, event-aware prediction system with RF and GB models, banded features, and diagnostics. The comparison plots (see `comparison_output/`) reveal a clear pattern: **both models compress predictions toward the mean and systematically underpredicts the magnitude of large positive returns**. This is expected behavior for tree-based regression on fat-tailed, event-driven financial data, but it limits practical utility.

This roadmap targets the root causes identified in the Version 2.2 analysis.

---

## 1. Root causes (from 2.2 analysis)

| # | Cause | Effect |
|---|-------|--------|
| 1 | Tree models average leaf values; cannot extrapolate | Predictions compressed into narrow band around the mean |
| 2 | Extreme returns are rare and event-driven | Model has too few training examples of large moves |
| 3 | Asymmetric / right-skewed return distribution | MSE loss makes it "safer" to predict moderate values |
| 4 | Heteroscedastic residuals (fan shape) | Error variance grows with actual return magnitude |
| 5 | Return clipping at ±3.0 piles up extreme targets | Clipped extremes still get averaged away by the model |

---

## 2. Milestones

### Milestone 5 – Target transformation

**Goal:** Compress the right tail so the model learns a more balanced mapping.

- **Log-return target:** Replace `y = (future - current) / current` with `y = log(1 + return)` (or `sign(r) * log(1 + |r|)` to handle negatives). This shrinks extreme positive returns closer to moderate ones, giving the loss function a fairer landscape.
- **Inverse transform at prediction time:** Convert predicted log-returns back to percentage returns and then to prices.
- **Re-run comparison:** Regenerate the same scatter / residual / histogram plots to confirm the compression effect narrows the residual fan and improves R² on the tails.

### Milestone 6 – Quantile or classification approach

**Goal:** Shift from point-estimate regression to probability buckets, which tree models handle better.

- **Bucket definition:** Define return buckets, e.g.:
  - Large drop (< -20%)
  - Small drop (-20% to -5%)
  - Flat (-5% to +5%)
  - Small rise (+5% to +20%)
  - Large rise (> +20%)
- **Classifier training:** Train a multi-class classifier (GB or RF) to predict the probability of each bucket. This converts the problem from "how much?" to "which regime?" — a much better fit for tree models.
- **Quantile regression (alternative):** Use `HistGradientBoostingRegressor(loss='quantile', quantile=...)` at multiple quantiles (e.g. 0.1, 0.5, 0.9) to produce prediction intervals rather than a single point estimate.
- **Evaluation:** Report classification accuracy, confusion matrix, and calibration plots (predicted vs observed probability per bucket).

### Milestone 7 – Asymmetric loss and regime detection

**Goal:** Penalize underestimation of large moves more heavily, and separate calm from volatile regimes.

- **Asymmetric loss:** Implement a custom GB objective (or use LightGBM / XGBoost with custom `obj` function) that penalizes under-prediction of positive returns more than over-prediction. This directly addresses the model's tendency to play it safe.
- **Regime classifier:** Train a binary classifier ("is this an event-driven spike scenario?") using event features, recent volatility, and momentum. Route each sample to a **calm-regime regressor** or a **spike-regime regressor**.
- **Evaluation:** Compare the two-model ensemble vs the single-model baseline on the same chronological split.

### Milestone 8 – Forward-looking event features

**Goal:** Give the model information about *upcoming* events, not just past/current ones.

- **Scheduled events:** Maintain a table of known upcoming CS2 events (majors announced months ahead, known operation cadences, Steam sale dates). Compute `days_until_next_major`, `days_until_next_sale`, etc.
- **Patch/announcement signals:** If feasible, add binary flags for recent patch notes or community announcements (e.g. scrape CS2 blog or HLTV news feed).
- **Feature importance check:** Verify that forward-looking features contribute meaningfully and don't just add noise.

### Milestone 9 – Validation, monitoring, and release

- **Rolling-window validation:** Replace the single 80/20 split with an expanding or sliding window (e.g. train on months 1–6, test on month 7; train on 1–7, test on 8; etc.) to measure stability.
- **Prediction interval reporting:** If quantile regression is used, surface confidence intervals in `predict_price` (e.g. return lower/upper bounds alongside the point estimate).
- **Dashboard / alerting:** Use `logs/prediction_log.csv` to build a lightweight dashboard showing prediction volume, average error by band/item-type, and drift alerts.
- **Documentation:** VERSION2.5.md release notes.

---

## 3. Priority and ordering

| Priority | Milestone | Rationale |
|----------|-----------|-----------|
| High | 5 (log-return target) | Easiest change; directly addresses the compression / fan shape |
| High | 6 (quantile / classification) | Better suited to the problem structure; actionable output |
| Medium | 7 (asymmetric loss / regime) | Bigger engineering effort; depends on 5/6 results |
| Medium | 8 (forward-looking events) | Data availability is the bottleneck |
| Low | 9 (validation / dashboard) | Polish; can run in parallel with 7–8 |

---

## 4. Success criteria

- **Scatter plot:** Predictions should follow the diagonal more closely, especially for actual returns above +50%.
- **Residual fan:** The upward-sloping wedge should narrow significantly.
- **R² improvement:** Target R² > 0.45 on the same 200-item chronological split.
- **Practical utility:** For the quantile / classification path, the model should correctly identify "large rise" items at least 2x better than a naive base-rate guess.
