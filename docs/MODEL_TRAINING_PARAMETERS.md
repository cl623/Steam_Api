# Model Training Parameters

## Overview
The price prediction model uses a **Random Forest Regressor** to predict future item prices based on historical price data and parsed item name features.

## Model Algorithm Parameters

### RandomForestRegressor
- **Algorithm**: Random Forest Regression (ensemble of decision trees)
- **n_estimators**: `100` (number of trees in the forest)
- **random_state**: `42` (for reproducibility)
- **Other parameters**: Using scikit-learn defaults:
  - `max_depth`: None (unlimited depth)
  - `min_samples_split`: 2
  - `min_samples_leaf`: 1
  - `max_features`: 'sqrt' (square root of total features)
  - `bootstrap`: True
  - `n_jobs`: None (single-threaded)

## Data Preparation Parameters

### Time Windows
- **lookback_days**: `7` (days of historical data to use for features)
- **prediction_days**: `7` (days ahead to predict)
- **Minimum data requirement**: `14` entries per item (lookback + prediction)

### Train/Test Split
- **test_size**: `0.2` (20% of data for testing)
- **random_state**: `42` (for reproducibility)
- **shuffle**: True (default)

### Feature Scaling
- **Scaler**: `StandardScaler` (z-score normalization)
  - Mean = 0, Standard Deviation = 1
  - Applied to all features before training

## Feature Set (22 Total Features)

### Price/Volume Features (5 features)
1. **price** - Current price at the time point
2. **price_ma7** - 7-day moving average of price
3. **price_ma30** - 30-day moving average of price (or 7-day if insufficient data)
4. **price_std7** - 7-day standard deviation of price (volatility measure)
5. **volume_ma7** - 7-day moving average of trading volume

### Item Type Features (7 features - one-hot encoded)
6. **type_weapon_skin** - Binary: 1 if weapon skin, 0 otherwise
7. **type_sticker** - Binary: 1 if sticker, 0 otherwise
8. **type_case** - Binary: 1 if case/capsule, 0 otherwise
9. **type_agent** - Binary: 1 if agent/operator skin, 0 otherwise
10. **type_gloves** - Binary: 1 if gloves, 0 otherwise
11. **type_knife** - Binary: 1 if knife, 0 otherwise
12. **type_other** - Binary: 1 if other item type, 0 otherwise

### Item Characteristics Features (10 features)
13. **is_weapon_skin** - Binary: 1 if weapon skin (duplicate of type_weapon_skin for emphasis)
14. **condition_quality** - Numeric: 0-5 scale
   - 5 = Factory New
   - 4 = Minimal Wear
   - 3 = Field-Tested
   - 2 = Well-Worn
   - 1 = Battle-Scarred
   - 0 = No condition specified
15. **is_stattrak** - Binary: 1 if StatTrak™ variant, 0 otherwise
16. **is_souvenir** - Binary: 1 if Souvenir variant, 0 otherwise
17. **has_sticker** - Binary: 1 if item name contains "sticker", 0 otherwise
18. **is_case** - Binary: 1 if case (duplicate of type_case)
19. **is_sticker** - Binary: 1 if sticker (duplicate of type_sticker)
20. **is_agent** - Binary: 1 if agent (duplicate of type_agent)
21. **is_gloves** - Binary: 1 if gloves (duplicate of type_gloves)
22. **is_knife** - Binary: 1 if knife (duplicate of type_knife)

## Feature Engineering Details

### Rolling Window Calculations
- **Adaptive windows**: If insufficient data, windows are reduced:
  - `window_7` = min(7, available_days - 1)
  - `window_30` = min(30, available_days - 1)
- **Handling NaN**: Standard deviation defaults to 0.0 if NaN

### Item Name Parsing
The model uses `ItemFeatureExtractor` to parse item names and extract:
- Item type (weapon skin, sticker, case, etc.)
- Weapon condition/quality (for weapon skins)
- Special variants (StatTrak, Souvenir)

## Target Variable

- **Target**: `future_price` - Price `prediction_days` (7) days in the future
- **Calculation**: `price_df['price'].shift(-prediction_days)`

## Model Evaluation Metrics

The model is evaluated using:
1. **MSE** (Mean Squared Error) - Average squared difference
2. **RMSE** (Root Mean Squared Error) - Square root of MSE (in price units)
3. **MAE** (Mean Absolute Error) - Average absolute difference (in price units)
4. **R² Score** - Coefficient of determination (explained variance)

## Example Usage

```python
from ml.price_predictor import PricePredictor

predictor = PricePredictor()
predictor.train_model('730')  # Train for CS2

# Predict future price
prediction = predictor.predict_price(
    game_id='730',
    item_name='AK-47 | Redline (Field-Tested)',
    current_price=10.0,
    current_volume=1000
)
```

## Notes

- The model requires at least 14 price history entries per item to train
- Features are automatically scaled using StandardScaler
- The model can handle items with varying amounts of historical data (adaptive windows)
- Item name parsing handles various formats including StatTrak™ and Souvenir prefixes
