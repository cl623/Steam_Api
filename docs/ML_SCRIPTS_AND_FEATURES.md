# ML Scripts, Model Training, and Features (Version 2.2)

This document describes the scripts, model training options, and new features available in the return-based, event-aware price prediction system (Version 2.2).

---

## 1. Scripts overview

| Script / module | Purpose |
|-----------------|--------|
| `scripts/train_model.py` | Train a single model (RF or default), save to a directory; supports sample/full mode and pause/resume. |
| `ml/model_comparison.py` | Compare RF vs GB on the same data split; optional GB hyperparameter tuning. |
| `scripts/run_comparison_with_plots.py` | Run comparison, print metrics table, and generate diagnostic plots (metrics bars, actual vs predicted, residuals). |
| `scripts/evaluate_model.py` | Detailed evaluation of a trained model (legacy script; uses random split). |
| `ml/model_diagnostics.py` | Load a saved model, rebuild features, and produce scatter/histogram/feature-importance plots. |

All commands below assume you are in the **project root** (the directory containing `ml/`, `scripts/`, and `data/`).

---

## 2. Model training

### 2.1 Training API (`PricePredictor.train_model`)

The core training logic lives in `ml/price_predictor.py`. Key parameters:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `game_id` | Game ID (e.g. `"730"` for CS2). | — |
| `max_items` | Cap on number of items to use; `None` = all items. | `None` |
| `pause_check` | Optional callable; if it returns True, training pauses (used by `train_model.py`). | `None` |
| `from_date` / `to_date` | Optional date range (YYYY-MM-DD) to restrict training data. | `None` |
| `use_event_window` | If True and dates not set, derive window from `cs2_events` table. | `False` |
| `pre_event_days` / `post_event_days` | Buffer days before/after event range when using event window. | 14 / 30 |
| `model_type` | `"rf"` (Random Forest) or `"gb"` (HistGradientBoostingRegressor). | `"rf"` |

**Return target:** Percentage return over the prediction horizon (e.g. 7 days), clipped to ±300% (`MAX_ABS_RETURN`). Samples with very low liquidity (`volume_ma7 < MIN_VOLUME_MA7`) are filtered out.

**Saving:** After training, call `predictor.save_models(path="...")` to write model and scaler to a directory. Load with `predictor.load_models(path="...")`.

**Example (event-window, GB, custom path):**

```python
from ml.price_predictor import PricePredictor

p = PricePredictor()
p.train_model(
    "730",
    max_items=500,
    use_event_window=True,
    model_type="gb",
)
p.save_models(path="models_events_2023_2024_Banded_GB")
```

### 2.2 Training script (`scripts/train_model.py`)

Convenience script that trains one model and saves it. It does **not** currently expose `model_type` or `use_event_window` on the command line; it uses defaults (RF, full date range) and saves to `models/`.

**Usage:**

```bash
python scripts/train_model.py                      # Full mode (all items)
python scripts/train_model.py --mode sample        # Sample mode (50 items)
python scripts/train_model.py --max-items 100      # Custom item limit
python scripts/train_model.py --pause-file pause.txt   # Pause/resume via file
```

- **Pause/resume:** Create the pause file to pause after the current item; delete it to resume. Ctrl+C saves progress and exits.
- **Output:** Model and scaler saved under `models/` (project root). For event-window + GB, use the API from code or extend the script with `--model-type gb` and `--use-event-window` and pass a custom `--save-path`.

---

## 3. Model comparison and plots

### 3.1 Comparison module (`ml/model_comparison.py`)

Builds data once with a chronological 80/20 split, trains both RF and GB, and reports MSE, RMSE, MAE, R², and MAPE (%) on the test set. Optional GB tuning via `GridSearchCV` and `TimeSeriesSplit`.

**Usage:**

```bash
# Compare RF vs GB (event window, game 730)
python -m ml.model_comparison --game-id 730 --max-items 500

# No event-window date filter
python -m ml.model_comparison --game-id 730 --no-event-window

# Tune GB hyperparameters (TimeSeriesSplit)
python -m ml.model_comparison --game-id 730 --tune-gb --n-jobs 2
```

**Programmatic use:** `compare_models(..., return_predictions=True)` returns `(metrics_df, y_test, preds_dict)` for custom plotting or analysis.

### 3.2 Comparison with plots (`scripts/run_comparison_with_plots.py`)

Runs the same comparison, prints the metrics table, and writes plots and a CSV into an output directory.

**Usage:**

```bash
# Default: event window, all items, output in comparison_output/
python scripts/run_comparison_with_plots.py

# Faster run with item limit
python scripts/run_comparison_with_plots.py --max-items 300

# Custom output directory
python scripts/run_comparison_with_plots.py --out-dir comparison_results

# Without event window
python scripts/run_comparison_with_plots.py --no-event-window --out-dir comparison_no_events
```

**Outputs:**

- **metrics.csv** – Table of MSE, RMSE, MAE, R², MAPE per model.
- **metrics_by_model.png** – Bar charts of each metric for RF vs GB.
- **actual_vs_predicted.png** – Scatter of actual vs predicted returns (one panel per model).
- **residuals_histogram.png** – Histogram of residuals (actual − predicted) per model.
- **residuals_vs_predicted.png** – Residuals vs predicted (heteroscedasticity check).

---

## 4. Diagnostics for a saved model

### 4.1 Model diagnostics (`ml/model_diagnostics.py`)

Loads a trained model from a directory, rebuilds the feature matrix with the current pipeline (optionally using the event window), and generates scatter, histogram, and feature-importance plots.

**Usage:**

```bash
python -m ml.model_diagnostics --model-dir models_events_2023_2024_Banded_GB --game-id 730
python -m ml.model_diagnostics --model-dir models --game-id 730 --max-items 200 --no-event-window
python -m ml.model_diagnostics --model-dir models --output-dir my_diagnostics
```

**Outputs** (under `<model-dir>/diagnostics/` or `--output-dir`):

- **scatter_y_true_vs_pred_730.png** – True vs predicted returns.
- **hist_returns_true_vs_pred_730.png** – Distribution of true vs predicted returns.
- **feature_importances_top10_730.png** – Top 10 feature importances (if the model exposes them).

Works with both RF and GB; feature importances are skipped for models that do not provide them.

---

## 5. New features in this version

### 5.1 Data and target

- **Return target:** Model predicts percentage return; `predict_price` converts back to a future price via `current_price * (1 + predicted_return)`.
- **Return clipping:** Targets clipped to `[-MAX_ABS_RETURN, MAX_ABS_RETURN]` (default ±3.0) in `prepare_data`.
- **Volume filter:** Rows with `volume_ma7 < MIN_VOLUME_MA7` (default 2.0) are dropped.
- **Chronological split:** Train/test split is time-based (e.g. last 20% by date); no shuffling.

### 5.2 Model types

- **RF** (`model_type='rf'`): `RandomForestRegressor` – baseline.
- **GB** (`model_type='gb'`): `HistGradientBoostingRegressor` – recommended for production; typically better R² and lower MAE.

### 5.3 Event-aware training

- **Event window:** When `use_event_window=True`, training dates are derived from the `cs2_events` table (with configurable pre/post buffers). Requires HLTV-derived `cs2_events` (and optionally `cs2_event_daily`) in the database.
- **Event features:** `prepare_data` merges `cs2_event_daily` by date; `predict_price` looks up event features for "today". See `docs/VERSION2.1.md` for the full feature list.

### 5.4 Stratification (bands)

- **Price band:** `_get_price_band(price, item_type)` – type-specific bands for weapon_skin, sticker, gloves, knife, other.
- **Volume band:** `_get_volume_band(volume_ma7)` – liquidity tiers.
- Both are included as features in training and prediction.

### 5.5 Prediction monitoring

- **Enable:** Set environment variable `PRICE_PREDICTOR_LOG_PREDICTIONS=1` (or `true`/`yes`).
- **Output:** Each successful `predict_price` call appends a row to `logs/prediction_log.csv` with:  
  `timestamp`, `game_id`, `item_name`, `current_price`, `predicted_price`, `predicted_return`, `item_type`, `price_band`, `volume_band`.

Use for auditing, drift analysis, or error breakdowns by item type/band.

### 5.6 Production recommendation

- **Model path:** e.g. `models_events_2023_2024_Banded_GB`.
- **Model type:** `model_type='gb'`.
- Load with `predictor.load_models(path="models_events_2023_2024_Banded_GB")` and call `predict_price(game_id, item_name)` as usual.

---

## 6. Quick reference: common workflows

**Train an event-aware GB model and save it:**

```python
from ml.price_predictor import PricePredictor
p = PricePredictor()
p.train_model("730", max_items=500, use_event_window=True, model_type="gb")
p.save_models(path="models_events_2023_2024_Banded_GB")
```

**Compare RF vs GB and generate plots:**

```bash
python scripts/run_comparison_with_plots.py --max-items 300 --out-dir comparison_output
```

**Evaluate a saved model and get diagnostics:**

```bash
python -m ml.model_diagnostics --model-dir models_events_2023_2024_Banded_GB --game-id 730
```

**Run predictions with logging enabled:**

```bash
set PRICE_PREDICTOR_LOG_PREDICTIONS=1
python -c "from ml.price_predictor import PricePredictor; p=PricePredictor(); p.load_models(path='models_events_2023_2024_Banded_GB'); print(p.predict_price('730', 'AK-47 | Redline (Field-Tested)'))"
```

See also **docs/VERSION2.0.md** (roadmap), **docs/VERSION2.1.md** (event integration), and **docs/VERSION2.2.md** (milestones 3–4 summary).
