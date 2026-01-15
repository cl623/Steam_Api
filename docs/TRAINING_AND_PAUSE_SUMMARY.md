# Training Process and Pause Functionality Summary

## How Training Works

### Overview

The `train_model.py` script trains a **Random Forest Regressor** to predict item prices 7 days in the future using:
- Historical price patterns (moving averages, volatility)
- Item characteristics (type, condition, StatTrak/Souvenir status)

### Step-by-Step Process

1. **Data Query** (5-10 seconds)
   - Queries database for items with sufficient price history (≥14 entries)
   - Filters to items with enough data for training

2. **Feature Extraction** (20-50 seconds for 50 items, minutes-hours for full)
   - For each item:
     - Fetches price history
     - Calculates 7-day and 30-day moving averages
     - Calculates price volatility (std7)
     - Parses item name to extract type, condition, etc.
     - Creates feature vectors (22 features per sample)
   - **Total**: ~245K samples from 50 items

3. **Data Splitting** (<1 second)
   - 80% training (196K samples)
   - 20% testing (49K samples)

4. **Feature Scaling** (<1 second)
   - StandardScaler: Normalizes all features to mean=0, std=1

5. **Model Training** (5-10 seconds)
   - Random Forest: 100 decision trees
   - Learns patterns from training data

6. **Evaluation** (<1 second)
   - Tests on held-out test set
   - Calculates metrics (R², MAE, RMSE)

7. **Model Saving** (<1 second)
   - Saves to `models/730_model.joblib`
   - Saves scaler to `models/730_scaler.joblib`

**Total Time**: ~30-60 seconds (sample mode), 10-30+ minutes (full mode)

## Pause Functionality

### Training Script (`train_model.py`)

**How to use**:

```bash
# Enable pause (optional - auto-enabled if pause.txt exists)
python scripts/train_model.py --mode sample --pause-file pause.txt

# Or just create pause.txt to enable pause
python scripts/train_model.py --mode sample
```

**How to pause**:
1. Create pause file: `echo. > pause.txt` (Windows) or `touch pause.txt` (Linux)
2. Training pauses after current item completes
3. Logs show: "PAUSE DETECTED: Training paused"

**How to resume**:
1. Delete pause file: `del pause.txt` (Windows) or `rm pause.txt` (Linux)
2. Training resumes automatically
3. Logs show: "RESUMING: Training resumed"

**How to stop**:
- Press `Ctrl+C` → Graceful shutdown (saves progress)

### Collection Script (`run_collector.py`)

**How to use**:

```bash
# Enable pause (optional - auto-enabled if pause_collector.txt exists)
python scripts/run_collector.py --pause-file pause_collector.txt

# Or just create pause_collector.txt to enable pause
python scripts/run_collector.py
```

**How to pause**:
1. Create pause file: `echo. > pause_collector.txt`
2. Collection pauses:
   - Main thread: After current listing fetch cycle
   - Worker threads: After current item
3. Logs show: "PAUSE DETECTED: Collection paused"

**How to resume**:
1. Delete pause file: `del pause_collector.txt`
2. Collection resumes automatically
3. Logs show: "RESUMING: Collection resumed"

**How to stop**:
- Press `Ctrl+C` → Graceful shutdown (waits for workers to finish)

## Technical Implementation

### Training Pause

- **Check point**: After each item is processed
- **Pause mechanism**: File-based (checks for pause file existence)
- **State preservation**: Continues from next item (no data loss)
- **Thread safety**: Uses locks to prevent race conditions

### Collection Pause

- **Check points**: 
  - Main thread: Every second in main loop
  - Worker threads: Before processing each item
- **Pause mechanism**: File-based (checks for pause file existence)
- **State preservation**: Queue and progress preserved
- **Thread safety**: Each thread checks independently

## Benefits

1. ✅ **No data loss**: Pauses at safe points
2. ✅ **Easy control**: Simple file create/delete
3. ✅ **Remote control**: Can pause from another terminal
4. ✅ **Automatic resume**: No manual intervention needed
5. ✅ **Graceful**: Doesn't interrupt current operations

## Example Workflow

### Training with Pause

```bash
# Terminal 1: Start training
python scripts/train_model.py --mode sample --pause-file pause.txt

# Terminal 2: Pause it
echo. > pause.txt

# Wait for "PAUSE DETECTED" message

# Terminal 2: Resume it
del pause.txt

# Training resumes automatically
```

### Collection with Pause

```bash
# Terminal 1: Start collection
python scripts/run_collector.py --pause-file pause_collector.txt

# Terminal 2: Pause it
echo. > pause_collector.txt

# Wait for "PAUSE DETECTED" message

# Terminal 2: Resume it
del pause_collector.txt

# Collection resumes automatically
```

## Key Points

- **Training calculates moving averages** during data preparation (Step 2)
- **Pause is file-based** - simple and reliable
- **Pause happens at safe points** - no data corruption
- **Resume is automatic** - just delete the pause file
- **Both scripts support pause** - consistent interface
