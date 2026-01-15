# How the Model Training Process Works

## Overview

The `train_model.py` script trains a Random Forest regression model to predict future item prices based on historical price data and parsed item characteristics.

## Training Process Flow

### 1. Data Preparation (`prepare_data()`)

```
┌─────────────────────────────────────────────────────────┐
│ Step 1: Query Database                                   │
├─────────────────────────────────────────────────────────┤
│ - Get all items for game_id (e.g., '730' for CS2)      │
│ - Filter items with sufficient price history (≥14)     │
│ - Limit items if in sample mode (default: 50 items)    │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ Step 2: Process Each Item                               │
├─────────────────────────────────────────────────────────┤
│ For each item:                                          │
│   1. Fetch price history from database                  │
│   2. Parse Steam timestamps ("Apr 01 2014 01: +0")     │
│   3. Calculate moving averages:                         │
│      - price_ma7 (7-day moving average)                 │
│      - price_ma30 (30-day moving average)               │
│      - price_std7 (7-day volatility)                   │
│      - volume_ma7 (7-day volume average)               │
│   4. Create target: future_price (7 days ahead)        │
│   5. Extract item name features (type, condition, etc.)│
│   6. Combine all features into feature vector          │
│   7. [PAUSE CHECK] - Check for pause file              │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ Step 3: Feature Matrix Creation                         │
├─────────────────────────────────────────────────────────┤
│ - Combine all feature vectors from all items            │
│ - Result: X (features), y (target prices)              │
│ - Example: 245,653 samples × 22 features                │
└─────────────────────────────────────────────────────────┘
```

### 2. Model Training (`train_model()`)

```
┌─────────────────────────────────────────────────────────┐
│ Step 1: Split Data                                      │
├─────────────────────────────────────────────────────────┤
│ - 80% training set (196,522 samples)                    │
│ - 20% test set (49,131 samples)                         │
│ - Random state: 42 (for reproducibility)                │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ Step 2: Feature Scaling                                 │
├─────────────────────────────────────────────────────────┤
│ - StandardScaler: z-score normalization                 │
│ - Mean = 0, Std = 1 for each feature                   │
│ - Fit on training data, transform both sets             │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ Step 3: Train Random Forest                            │
├─────────────────────────────────────────────────────────┤
│ - Algorithm: RandomForestRegressor                      │
│ - n_estimators: 100 trees                                │
│ - random_state: 42                                      │
│ - Training time: ~10-30 seconds (sample mode)            │
│ - Training time: ~minutes-hours (full mode)             │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ Step 4: Evaluate Model                                 │
├─────────────────────────────────────────────────────────┤
│ - Predict on test set                                   │
│ - Calculate metrics:                                    │
│   * MSE (Mean Squared Error)                            │
│   * RMSE (Root Mean Squared Error)                      │
│   * MAE (Mean Absolute Error)                           │
│   * R² Score (coefficient of determination)             │
│ - Show feature importance (top 5 features)               │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ Step 5: Save Model                                      │
├─────────────────────────────────────────────────────────┤
│ - Save model: models/730_model.joblib                   │
│ - Save scaler: models/730_scaler.joblib                 │
│ - Models can be loaded later for predictions            │
└─────────────────────────────────────────────────────────┘
```

## Feature Engineering Details

### Price/Volume Features (5 features)

1. **price**: Current price at time point
2. **price_ma7**: 7-day moving average (captures short-term trend)
3. **price_ma30**: 30-day moving average (captures long-term trend)
4. **price_std7**: 7-day standard deviation (measures volatility)
5. **volume_ma7**: 7-day volume moving average (trading activity)

### Item Name Features (17 features)

Parsed from item name using `ItemFeatureExtractor`:
- Item type flags (weapon_skin, sticker, case, agent, etc.)
- Condition quality (0-5 scale)
- Special variants (StatTrak, Souvenir)
- Boolean flags for item characteristics

**Total**: 22 features per sample

## Training Time

- **Sample mode (50 items)**: ~30-60 seconds
  - Data preparation: ~25-50 seconds
  - Model training: ~5-10 seconds
  
- **Full mode (all items)**: Minutes to hours
  - Depends on number of items (1,550+ items)
  - Depends on price history size (3M+ entries)
  - Can take 10-30+ minutes

## Memory Usage

- **Sample mode**: ~100-500 MB
- **Full mode**: ~500 MB - 2 GB (depends on data size)

## Output

After training, the script:
1. Saves model files to `models/` directory
2. Prints performance metrics
3. Tests predictions on sample items
4. Shows feature importance

## Key Parameters

- **lookback_days**: 7 (days of history to use)
- **prediction_days**: 7 (days ahead to predict)
- **test_size**: 0.2 (20% for testing)
- **n_estimators**: 100 (number of trees)
- **random_state**: 42 (for reproducibility)

## Pause/Resume Functionality

The training script supports pause/resume:

1. **Enable pause**: `--pause-file pause.txt` (or create `pause.txt`)
2. **Pause**: Create the pause file → training pauses after current item
3. **Resume**: Delete the pause file → training resumes automatically
4. **Stop**: Press Ctrl+C → graceful shutdown with progress saved

See `docs/PAUSE_FUNCTIONALITY.md` for details.
