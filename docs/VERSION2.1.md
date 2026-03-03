### Version 2.1 – Event-Aware Return Model

This version extends the price prediction system to be **time-aware, return-based, and CS2-event-aware** over the HLTV dataset window (2023–09–17 to 2024–10–24).

---

### 1. Scope of Version 2.1

- **Target**: Still predicts **percentage returns** over a fixed horizon (e.g., 7 days), not raw prices.
- **Time window**: Training and evaluation are restricted to the overlap between:
  - CS2 marketplace data in `price_history`, and
  - CS2 events from the HLTV dataset (`cs2_events`), plus configurable pre/post buffers.
- **Models**:
  - Baseline random forest model (no events) remains in `models/`.
  - Event-aware model version is saved separately (e.g. `models_events_2023_2024/`) and uses the new event features.

---

### 2. HLTV Event Integration

- **Dataset**: `ilyazored/hltv-match-resultscs2` from Kaggle (via `kagglehub`).
- **Processing module**: `ml/cs2_event_features.py`:
  - Parses HLTV `time` strings like `\"Results for October 24th 2024\"` into standardized dates.
  - Aggregates matches into an **event table** (`cs2_events`), with `start_date`, `end_date`, `num_matches`, and `stars` per event.
  - Builds a **daily feature table** (`cs2_event_daily`) with:
    - `num_events`
    - `max_stars`
    - `has_event_today`
    - `is_major_today` (stars ≥ 4)
    - `max_stars_prev_7d`
    - `max_stars_prev_30d`

These tables are written into `data/market_data.db` when available.

---

### 3. Event-Window-Constrained Training

- **Price history filtering**:
  - `PricePredictor.prepare_data(...)` now accepts `from_date` and `to_date` and filters each item’s `price_df` to that window before feature engineering.
  - This ensures all features and targets are drawn from the same **event-aware regime**.
- **Automatic event window derivation**:
  - `PricePredictor.train_model(...)` can be called with `use_event_window=True`.
  - If `from_date` / `to_date` are not provided, it derives:
    - `from_date = min(start_date in cs2_events) - pre_event_days`
    - `to_date = max(end_date in cs2_events) + post_event_days`
  - Defaults: `pre_event_days = 14`, `post_event_days = 30`, capturing pre-event hype and post-event decay.

This separates the **event-era model** from any older, pre-CS2 or non-event periods.

---

### 4. New Feature Set (Training & Prediction)

On top of the existing price and item features, the per-sample feature vector now includes:

- **Momentum & time features**:
  - `ret_7`, `ret_30`: recent percentage returns.
  - `day_of_week`, `month`: calendar context.
- **Event features (from `cs2_event_daily`)**:
  - `num_events`: number of CS2 events active on that date.
  - `has_event_today`: indicator for any event.
  - `is_major_today`: indicator for ≥4-star events.
  - `max_stars_prev_7d`: highest star level seen in the previous 7 days.
  - `max_stars_prev_30d`: highest star level seen in the previous 30 days.

These features are:

- Joined **by date** inside `prepare_data` when constructing `price_df`.
- Looked up again at **prediction time** in `predict_price`, so the model sees a consistent structure in both training and inference.

---

### 5. Diagnostics and Plots

- **New diagnostics module**: `ml/model_diagnostics.py`
  - Loads an existing trained model + scaler from a given directory.
  - Rebuilds the feature matrix using the current pipeline (optionally constrained to the event window).
  - Produces:
    - **Scatter plot** of `y_true` vs. `y_pred` (returns).
    - **Histogram** of true vs. predicted returns.
    - **Top-10 feature importances** bar chart.
  - Output is written into `<model_dir>/diagnostics/` by default.

Example usage:

```bash
python -m ml.model_diagnostics --model-dir models_events_2023_2024 --game-id 730
```

---

### 6. Known Limitations and Next Steps

- **Model class**: Still a `RandomForestRegressor` on percentage returns; performance is currently noisy with weak R², indicating the need for:
  - Stronger regularization and/or a switch to **gradient-boosted trees** (XGBoost/LightGBM/CatBoost).
  - Return clipping or a log(1+return) target to tame extreme outliers.
  - Volume-based filtering to remove illiquid, high-noise items.
- **Validation**: Only a single 80/20 chronological split is implemented; a rolling-window validation scheme would better capture stability over time.

These improvements are candidates for **Version 2.2**, with a focus on model class upgrades, robust targets, and more granular validation.

