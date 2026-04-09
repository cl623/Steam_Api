# Project summary: before the course project (pre–deep learning)

This document describes the Steam Market **CS2 (app 730)** system **up to the point where deep learning work began**—that is, the web application, data pipeline, and **tabular** machine learning baselines. It is the foundation the course project builds on.

For what changed **during** the course project (LSTM, evaluation harness, etc.), see [COURSE_PROJECT_PROGRESS.md](COURSE_PROJECT_PROGRESS.md).

---

## 1. Goals

- **Browse and track** Steam Community Market listings with price history.
- **Collect** historical prices and volumes into a local **SQLite** database (`data/market_data.db`).
- **Predict** short-horizon **price returns** (not only levels) using engineered features and **scikit-learn** tree models.
- **Simulate** a simple weekly trading strategy with **fees** using those predictions.

---

## 2. Application and data layer

- **Flask** web app (`app/`, `run.py`): listings, cart, charts, settings (including Steam **cookies** for authenticated requests).
- **Collector** (`collector/market_collector.py`, `scripts/run_collector.py`): background ingestion with rate-limit awareness; persists to SQLite.
- **Database**: items, `price_history`, and—where present—event-related tables such as `**cs2_events`** / `**cs2_event_daily**` for tournament-aware features.
- **Supporting scripts**: migrations (`migrate_db.py`, `migrate_ml_schema.py`), cookie tests (`test_cookies.py`), duplicate checks, debug utilities.

---

## 3. Feature engineering and targets (tabular)

Central logic lives in `**ml/price_predictor.py`** and `**ml/feature_extractor.py**`:

- **Per-day rows** with price, 7/30-day moving averages, volatility, volume MA, momentum (`ret_7`, `ret_30`), calendar features, **event features** (e.g. events today, major flag, star history from `cs2_event_daily` where available).
- **Price and volume bands** (type-specific tiers) to separate cheap fillers from premium liquidity regimes.
- **Target**: **7-day percentage return**, **clipped** to a bounded range, with a **minimum liquidity** filter on `volume_ma7`.
- `**ItemFeatureExtractor`**: static signals from `market_hash_name` (weapon vs sticker vs case, StatTrak, etc.).

---

## 4. Tabular models and evaluation

- **Random Forest** (`RandomForestRegressor`) and **histogram gradient boosting** (`HistGradientBoostingRegressor`) as the main production-style baselines.
- **Training** via `PricePredictor.train_model` and convenience script `**scripts/train_model.py`** (save under `models/` or custom paths).
- **Head-to-head comparison** of RF vs GB on the **same chronological split**: `**ml/model_comparison.py`** and `**scripts/run_comparison_with_plots.py**` (metrics: MSE, RMSE, MAE, R², MAPE on returns; optional plots).
- **Documented results** for event-window, banded models: see **[MODEL_SUMMARY.md](MODEL_SUMMARY.md)** (e.g. ~84k samples / 200 items in that study; GB slightly better on MAE/MAPE; both **compress** predictions and **under-call** large positive moves).

---

## 5. Backtesting (tabular only)

- `**scripts/backtest.py`**: weekly **top-K** allocation by predicted **7-day return**, **~15% fee** assumption, hold **7 days**, repeat over a test window; supports **RF** and **GB** (not the neural model).
- Prior V2 work (per **VERSION3.0.md** context) also refined **liquidity**, **deduplication**, and **minimum price** behavior in that simulation.

---

## 6. Documentation and iteration (V2.x)

Multiple docs in `docs/` capture schema reviews, training parameters, accuracy analyses, rate limits, threading, and **roadmaps** (e.g. **VERSION2.5** ideas: log returns, asymmetric loss, classification—many of these ideas later informed the **V3 / LSTM** design described in **VERSION3.0.md**).

---

## 7. Limitations recognized before DL

- Tree models **average in leaves** → predictions cluster near the **mean return**; **fat-tailed** upside is hard to capture.
- **MSE** on returns encourages “safe” mid-range predictions.
- **Event features** were largely **backward-looking**; the biggest moves often tie to **future** operations and hype.
- **Single time-step** tabular rows do not encode a long **sequence** of market state the way a recurrent model can.

These motivated the **course project** shift to **sequences**, **log-return targets**, **bucket classification**, and **stricter evaluation splits**—see the companion document.