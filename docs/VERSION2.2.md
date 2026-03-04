# Version 2.2 – Model Comparison, Tuning, and Monitoring

This document summarizes **Milestone 3** (model comparison and GB tuning) and **Milestone 4** (model selection, monitoring, and release notes) for the return-based, event-aware price prediction system.

---

## 1. Milestone 3 – Model Comparison and Tuning

### 1.1 Return Clipping and Volume Filter (pre-M3)

- **Return clipping**: Targets are clipped to `[-MAX_ABS_RETURN, MAX_ABS_RETURN]` (default 3.0, i.e. ±300%) in `prepare_data` to reduce impact of extreme outliers.
- **Volume filter**: Samples with `volume_ma7 < MIN_VOLUME_MA7` (default 2.0) are dropped to avoid illiquid, noisy items.

### 1.2 Model Types

- **RF** (`model_type='rf'`): `RandomForestRegressor` – baseline.
- **GB** (`model_type='gb'`): `HistGradientBoostingRegressor` – typically better R² and lower MAE on the same setup.

Both use the same feature pipeline (price/volume bands, event features, momentum, time, item one-hots) and chronological 80/20 split.

### 1.3 Comparison Script

- **Module**: `ml/model_comparison.py`
- **Behavior**: Builds data once with the same chronological split, trains RF and GB, and prints a table: MSE, RMSE, MAE, R², MAPE (%) on returns.

**Usage:**

```bash
# Compare RF vs GB (event window, default game 730)
python -m ml.model_comparison --game-id 730 --max-items 500 --use-event-window

# Without event-window date filter
python -m ml.model_comparison --game-id 730 --no-event-window

# Optional: tune GB hyperparameters (TimeSeriesSplit)
python -m ml.model_comparison --game-id 730 --tune-gb --n-jobs 2
```

- **Tuning**: `--tune-gb` runs a small `GridSearchCV` over `max_depth`, `learning_rate`, `max_iter` using `TimeSeriesSplit` (no shuffling) and reports best params and CV MSE.

---

## 2. Milestone 4 – Production Choice and Monitoring

### 2.1 Recommended Production Model

- **Model path**: `models_events_2023_2024_Banded_GB` (or the path you used when saving the event-window, banded, GB model).
- **Model type**: `model_type='gb'` (`HistGradientBoostingRegressor`).
- **Training**: Event window derived from `cs2_events`, banded features (price/volume), return target with clipping, volume filter, chronological split.

To use in code:

```python
from ml.price_predictor import PricePredictor

p = PricePredictor()
p.train_model("730", model_type="gb", use_event_window=True, ...)  # or load_models
p.save_models(path="models_events_2023_2024_Banded_GB")
# For inference, load with:
p.load_models(path="models_events_2023_2024_Banded_GB")
predicted_price = p.predict_price("730", "Some Item Name")
```

### 2.2 Prediction Monitoring

- **Trigger**: Set environment variable `PRICE_PREDICTOR_LOG_PREDICTIONS=1` (or `true`/`yes`) to enable logging of each `predict_price` call.
- **Output**: Appends one row per prediction to `logs/prediction_log.csv` with:
  - `timestamp`, `game_id`, `item_name`, `current_price`, `predicted_price`, `predicted_return`, `item_type`, `price_band`, `volume_band`.

Use this for auditing, drift checks, or later analysis of prediction errors by item type/band.

---

## 3. Summary of Changes in 2.2

| Area              | Change |
|-------------------|--------|
| Targets           | Return clipping (`MAX_ABS_RETURN`), volume filter (`MIN_VOLUME_MA7`) |
| Models            | RF + GB option; GB recommended for production |
| Comparison        | `ml/model_comparison.py`: same-split RF vs GB metrics + optional GB tuning |
| Comparison+plots  | `scripts/run_comparison_with_plots.py`: metrics table + bar/scatter/residual plots |
| Production        | Documented path and `model_type='gb'` for event-window banded model |
| Monitoring        | Optional prediction logging to `logs/prediction_log.csv` via env var |
| Diagnostics       | `model_diagnostics.py` supports loaded GB models and guards `feature_importances_` |

**Full script and training reference:** See **docs/ML_SCRIPTS_AND_FEATURES.md** for detailed usage of all scripts, `train_model` API (including `model_type`, `use_event_window`), comparison-with-plots outputs, diagnostics, and new features.

---

## 4. Next Steps (beyond 2.2)

- Rolling or expanding-window validation for more robust metrics.
- Periodic retraining and A/B comparison of saved models.
- Alerts or dashboards on prediction volume and error by band (using `prediction_log.csv`).
