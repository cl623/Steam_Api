### Version 2.0 – Model Quality Issues and Phase 2 Roadmap

This document explains **why the current model underperforms** and defines the **next milestones** for the price prediction system.

---

### 1. Root Causes of Weak Performance

#### 1.1 Data Leakage (Time-Series Being Shuffled)

In `PricePredictor.train_model`, the data is split with a random shuffle:
`X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)`

**Problem:** For time-series data, random splitting leaks future information into the training set. The model can see 2025 prices while being evaluated on 2023–2024, which makes offline metrics look much better than real-world performance.

**Required change:**
- Replace random splitting with **chronological splitting**:
  - Train on earlier history (e.g., all data up to a cutoff date).
  - Validate/test only on **later** data (e.g., the most recent 3–6 months).
- Implementation options:
  - Use `TimeSeriesSplit` from `sklearn.model_selection`, or
  - Manually sort by timestamp and slice the last N% of rows as the test period.

#### 1.2 Predicting Absolute Price Instead of Relative Move

The current target in `prepare_data` is `future_price` (a raw price in currency units).

**Problem:** The same absolute error has very different meaning across items. A \$5 error on a \$1,500 knife is excellent; a \$5 error on a \$0.05 skin is unusable. The loss function treats these equally.

**Required change:**
- Redefine the target as **percentage return** instead of raw price:
  - \( y = \frac{Price_{future} - Price_{current}}{Price_{current}} \)
- During inference (in `predict_price`), convert the predicted return back to a price:
  - \( \hat{Price}_{future} = Price_{current} \times (1 + \hat{y}) \)
- This lets the model learn patterns like “this type of item tends to move +3% in 7 days” regardless of the current absolute price.

#### 1.3 Missing Contextual and Market Regime Features

`ItemFeatureExtractor` currently focuses on static properties (weapon type, StatTrak, condition, etc.). The Steam market is also strongly driven by **time-dependent context** (sales, operations, majors, general market hype).

**Required additions:**
- **Time-based features** (per observation):
  - Day of week (one-hot or cyclical encoding).
  - Month or season (captures Summer/Winter sales effects).
  - Days since last major CS2 operation or big patch.
- **Event flags:**
  - `is_steam_sale_period`
  - `is_major_tournament_month`
- **Market dynamics / momentum:**
  - Already have `price_std7` as a volatility proxy.
  - Add simple momentum features such as:
    - 7-day return: \( \frac{price_{t} - price_{t-7}}{price_{t-7}} \)
    - 30-day return where data exists.

These can be computed alongside the existing rolling-window features in `prepare_data` using the same historical price windows.

---

### 2. Model and Metric Upgrades

#### 2.1 Switch to Gradient-Boosted Trees

For tabular data with mixed numeric and categorical-like features, **gradient boosting** models (XGBoost, LightGBM, or CatBoost) typically outperform Random Forests.

**Planned change:**
- Replace `RandomForestRegressor` with a gradient-boosted model, starting with a simple configuration (e.g., XGBoost or LightGBM with modest depth and learning rate).
- Keep the existing `StandardScaler` only if experiments show benefit; tree-based models usually do **not** require feature scaling.

#### 2.2 Use Scale-Aware Evaluation Metrics

**Problem:** Using `mean_squared_error` on raw prices overweights a few high-ticket items and masks poor relative performance on cheap items.

**Planned change:**
- Report metrics in terms of **relative error**:
  - Mean Absolute Percentage Error (MAPE).
  - Median Absolute Percentage Error (more robust to outliers).
- Optionally keep RMSE/MAE on **returns**, not raw prices, as secondary diagnostics.

---

### 3. Phase 2 Milestones

#### Milestone 1 – Fix Data Pipeline and Targets

1. **Chronological split:**
   - Sort samples by timestamp.
   - Implement train/validation/test splits that respect time order (no leakage).
2. **Return-based target:**
   - Modify `prepare_data` to compute percentage returns instead of `future_price`.
   - Update `predict_price` to map predicted returns back to prices.
3. **Backtest harness:**
   - Build a simple backtest over the last N months to simulate “buy now, sell in X days” behavior using model predictions.

#### Milestone 2 – Feature Expansion

1. **Time features (now):**
   - Derive day-of-week, month, and season (or similar) from timestamps and feed them into the model.
2. **Momentum & volatility features (now):**
   - Add rolling returns (e.g., 7-day and 30-day returns) and extended volatility measures alongside the existing moving averages.
3. **Significant event timeline (later, separate step):**
   - Maintain a dedicated “significant CS2 events” timeline (majors, operations, big patches, sales) with precise dates.
   - Later, join this table onto the price history to create event-driven flags such as `is_major_tournament_month`, `is_operation_window`, and `is_steam_sale_period`.
4. **Feature importance review:**
   - Re-train and inspect feature importance to confirm that new contextual and momentum features contribute meaningfully, and to guide which event features to prioritize once the event timeline is in place.

#### Milestone 3 – Model Upgrade to Gradient Boosting

1. **Introduce boosted model:**
   - Add a new training path (e.g., `GradientBoostedPricePredictor`) using XGBoost/LightGBM.
2. **Hyperparameter tuning (lightweight):**
   - Grid or random search over key parameters (depth, learning rate, estimators) using the time-aware validation split.
3. **Compare against baseline:**
   - Side-by-side metrics: Random Forest vs. Gradient Boosting on the same time-based test window.

#### Milestone 4 – Validation, Monitoring, and Release

1. **Model selection for production:**
   - Choose the model with the best **out-of-sample percentage error** and most stable behavior across item price buckets.
2. **Monitoring hooks:**
   - Log prediction errors over time by item type and price band for live or periodically refreshed predictions.
3. **Documentation & versioning:**
   - Record final hyperparameters, feature set, and data cutoffs for Version 2.0.
   - Tag the release and update any user-facing descriptions to reflect “return-based, time-aware” predictions.

This roadmap should take the model from “coin flip with leakage” to a **time-respecting, return-based, and context-aware price forecaster** that is much closer to how real financial models are built.