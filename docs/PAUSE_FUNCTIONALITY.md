# Pause/Resume Functionality

## Overview

Both `train_model.py` and `run_collector.py` now support pause/resume functionality using file-based pause signals.

## How It Works

### File-Based Pause System

- **Create pause file** → Process pauses after current operation
- **Delete pause file** → Process resumes automatically
- **Ctrl+C** → Graceful shutdown (saves progress)

## Training Script (`train_model.py`)

### Usage

```bash
# Enable pause functionality
python scripts/train_model.py --pause-file pause.txt

# Or use default pause file (pause.txt in current directory)
python scripts/train_model.py --mode sample
# Then create pause.txt to pause
```

### How to Pause Training

1. **During training**, create the pause file:
   ```bash
   # Windows PowerShell
   New-Item -Path pause.txt -ItemType File
   
   # Or just create an empty file named "pause.txt"
   ```

2. **Training will pause** after finishing the current item
   - Logs: "PAUSE DETECTED: Training paused"
   - Logs: "Delete 'pause.txt' to resume training"

3. **To resume**, delete the pause file:
   ```bash
   # Windows PowerShell
   Remove-Item pause.txt
   ```

4. **Training resumes automatically** when file is deleted
   - Logs: "RESUMING: Training resumed"

### Example

```bash
# Start training
python scripts/train_model.py --mode sample --pause-file pause.txt

# In another terminal, pause it
echo. > pause.txt

# Later, resume it
del pause.txt
```

## Collection Script (`run_collector.py`)

### Usage

```bash
# Enable pause functionality
python scripts/run_collector.py --pause-file pause_collector.txt

# Or use default pause file (pause_collector.txt)
python scripts/run_collector.py
# Then create pause_collector.txt to pause
```

### How to Pause Collection

1. **During collection**, create the pause file:
   ```bash
   # Windows PowerShell
   New-Item -Path pause_collector.txt -ItemType File
   ```

2. **Collection will pause**:
   - Main thread pauses after current cycle
   - Worker threads pause after current item
   - Logs: "PAUSE DETECTED: Collection paused"

3. **To resume**, delete the pause file:
   ```bash
   Remove-Item pause_collector.txt
   ```

4. **Collection resumes automatically**
   - Logs: "RESUMING: Collection resumed"

### Example

```bash
# Start collection
python scripts/run_collector.py --pause-file pause_collector.txt

# In another terminal, pause it
echo. > pause_collector.txt

# Later, resume it
del pause_collector.txt
```

## Technical Details

### Training Script Pause

- **Check frequency**: After each item is processed
- **Pause point**: Between items (safe point)
- **Resume**: Automatic when file is deleted
- **State**: No state is lost (continues from next item)

### Collection Script Pause

- **Check frequency**: 
  - Main thread: Every second in main loop
  - Worker threads: Before processing each item
- **Pause point**: 
  - Main thread: Between listing fetch cycles
  - Workers: Between items
- **Resume**: Automatic when file is deleted
- **State**: Queue and progress are preserved

## Benefits

1. **No data loss**: Pauses at safe points
2. **Easy control**: Simple file create/delete
3. **Remote control**: Can pause from another terminal/script
4. **Graceful**: Doesn't interrupt current operations
5. **Automatic resume**: No manual intervention needed

## Use Cases

1. **Resource management**: Pause when system needs resources
2. **Scheduled maintenance**: Pause during maintenance windows
3. **Rate limit handling**: Pause if hitting rate limits manually
4. **Debugging**: Pause to investigate issues
5. **Testing**: Pause to test other components

## Limitations

- **Not instant**: Pauses after current operation completes
- **File system**: Requires file system access
- **Single pause file**: One pause file per process

## Best Practices

1. **Use descriptive pause file names**: `pause_train.txt`, `pause_collector.txt`
2. **Check pause file location**: Make sure it's in the working directory
3. **Monitor logs**: Check logs to confirm pause/resume
4. **Don't delete during operation**: Wait for "paused" message before deleting

## Example Workflow

```bash
# Terminal 1: Start training
python scripts/train_model.py --mode sample --pause-file pause.txt

# Terminal 2: Pause training
echo. > pause.txt

# Wait for "PAUSE DETECTED" message in Terminal 1

# Terminal 2: Resume training
del pause.txt

# Training resumes automatically
```
