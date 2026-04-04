# Model Training Summary and Comparison

## 1. Models trained

We trained and saved three generations of models, each building on the last. All predict **7-day percentage returns** on CS2 (game 730) Steam market items using a chronological 80/20 train/test split.

### 1.1 Event-aware RF (`models_events_2023_2024`)

- **Algorithm:** Random Forest (`RandomForestRegressor`, 200 trees).
- **Features:** Price, 7/30-day moving averages, volatility, volume, 7/30-day momentum returns, day-of-week, month, and HLTV event features (`num_events`, `has_event_today`, `is_major_today`, `max_stars_prev_7d`, `max_stars_prev_30d`).
- **Training window:** Event-aware (2023-09 to 2024-10, derived from `cs2_events` with 14-day pre / 30-day post buffers).
- **Notes:** First model to use return-based targets and event features. Weak R² and noisy predictions, but established the baseline pipeline.

### 1.2 Banded RF (`models_events_2023_2024_Banded`)

- **Algorithm:** Random Forest (same hyperparameters).
- **Features:** All of the above, plus **price band** (type-specific thresholds for weapon skins, stickers, gloves, knives) and **volume band** (liquidity tiers). Also includes return clipping (`MAX_ABS_RETURN = 3.0`) and a volume filter (`MIN_VOLUME_MA7 = 2.0`).
- **Training window:** Same event-aware window.
- **Notes:** Band features help the model distinguish cheap fillers from premium items. Return clipping and volume filter reduce noise from extreme outliers and illiquid items.

### 1.3 Banded GB (`models_events_2023_2024_Banded_GB`)

- **Algorithm:** Histogram-based Gradient Boosting (`HistGradientBoostingRegressor`, max_depth=6, learning_rate=0.05, 300 iterations).
- **Features:** Identical to Banded RF.
- **Training window:** Same event-aware window.
- **Notes:** Gradient Boosting typically learns more complex interactions than RF. This is the recommended production model.

---

## 2. Head-to-head comparison (200 items, event window)

Both RF and GB were trained on the **exact same chronological split** (84,361 samples, 33 features) using `scripts/run_comparison_with_plots.py`.

| Metric | RF | GB | Better |
|--------|-----|-----|--------|
| MSE | 0.187 | 0.191 | RF |
| RMSE | 0.433 | 0.437 | RF |
| MAE | 0.238 | **0.222** | **GB** |
| R² | **0.353** | 0.339 | **RF** |
| MAPE (%) | 274.9 | **221.4** | **GB** |

### Interpretation

- **RF wins on variance-based metrics** (MSE, RMSE, R²) by a small margin. It explains ~35% of the variance in test-set returns.
- **GB wins on absolute and relative error** (MAE, MAPE). Its predictions are closer to actual returns on average, especially in percentage terms.
- The difference between the two is modest. Both models cluster predictions in a narrow range around the mean return and struggle with extreme moves.

---

## 3. Diagnostic findings

Four diagnostic plots were generated (in `comparison_output/`):

### Actual vs predicted scatter

Both models show a **compressed cloud**: predictions span roughly -1.0 to +1.0, while actual returns span -1.0 to +3.0. The cloud sits below the perfect-fit diagonal for large actual returns, meaning both models **undershoot positive extremes**.

### Residual histogram

Residuals (actual minus predicted) are roughly centered near zero but have a **long right tail** — the model systematically underpredicts large positive moves.

### Residuals vs predicted

A classic **heteroscedastic fan shape**: residual variance increases with predicted return. When the model predicts a small return, the actual outcome can be anything. This upward-sloping wedge is the signature of mean-regression on fat-tailed data.

### Metrics bar chart

Visually confirms that RF and GB are close on all metrics, with RF slightly better on R² and GB slightly better on MAE/MAPE.

---

## 4. Why both models struggle with extremes

1. **Tree models average leaf values** — they cannot extrapolate beyond the range of training data, so predictions compress toward the mean.
2. **Extreme returns are rare and event-driven** — operations, case discontinuations, and tournament hype create spikes that have too few training examples.
3. **Asymmetric distribution** — CS2 returns have a long right tail; MSE loss makes it "safer" for the model to predict moderate values.
4. **Return clipping at ±3.0** reinforces the pattern by piling up the most extreme targets at the boundary.
5. **Backward-looking event features** — the model knows what *happened* recently but not what *will* happen next (upcoming events drive the biggest moves).

---

## 5. Recommendation

**For production:** Use the **Banded GB model** (`models_events_2023_2024_Banded_GB`, `model_type='gb'`). While RF has a marginally higher R², GB's lower MAE and MAPE mean its predictions are more practically useful — closer to actual outcomes on average and less prone to large percentage misses.

**For the next version (2.5):** The fundamental limitation is that point-estimate regression on fat-tailed returns compresses predictions. The roadmap (`docs/VERSION2.5_ROADMAP.md`) targets this with log-return targets, quantile/classification approaches, asymmetric loss functions, and forward-looking event features.
