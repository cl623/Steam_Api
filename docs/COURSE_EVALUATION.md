# Course project: evaluation and honest metrics

This note supports the **LSTM vs tabular** work for a student report. It explains correlation between samples, the new **item holdout** split, how to compare models fairly, and what to say about limitations.

## 1. Why many windows do not mean “many independent trials”

Each Steam item generates one sliding window per day (after filters). Neighboring windows share almost the same price path. Treating ~250k windows as i.i.d. samples **overstates** how much information you have. A more honest count is closer to **(number of items) × (effective time range)**, not the raw window count.

The legacy **pooled** split (`split_mode=pooled`) sorts all items’ windows into one list and takes the first 80% for training. That can put windows from the **same item** in both train and test, which inflates test scores relative to **new skins**.

## 2. Item holdout (`split_mode=item_holdout`)

`build_dataloaders` in `ml/deep_learning/dataset.py` can assign **entire `market_hash_name` values** to train or test using `--holdout-fraction` and `--holdout-seed`. Test metrics then measure **generalization to unseen items**, which is stricter and usually more meaningful for a marketplace story.

Training logs **macro-F1** (all buckets weighted equally) alongside accuracy so a dominant “flat” class does not hide poor performance on rare buckets.

`scripts/train_lstm.py` writes `split_meta.json` next to checkpoints so you can reproduce the same split for `scripts/compare_lstm_vs_tabular.py` and `scripts/eval_lift_lstm.py`.

## 3. Comparing LSTM to Random Forest / Gradient Boosting

- Tabular models (`ml/price_predictor.py`) predict **clipped percentage returns** with one row per day.
- The LSTM predicts **buckets** of **log-return** targets.

They are **not** aligned row-by-row: different feature construction and different numbers of rows per item. A fair high-level comparison is:

1. **Same held-out item names** (item holdout).
2. **Bucket metrics**: map tabular predictions to buckets with `returns_to_bucket_labels` in `ml/deep_learning/buckets.py`, then report **accuracy** and **macro-F1** vs true bucket labels.
3. **MAE in log-return space**: transform clipped returns with `clipped_returns_to_log_returns`; for the LSTM use `expected_log_return_from_probs` as a point estimate.

Run:

```bash
python scripts/compare_lstm_vs_tabular.py --max-items 50 --holdout-seed 42 \
  --lstm-checkpoint models_lstm/best_model.pt
```

Tabular rows use the same `max_items` cap and, if you pass `--use-event-window`, the same approximate calendar window as the LSTM loader.

## 4. Ablation experiments

`scripts/run_course_ablations.py` runs a few **short** trainings and appends validation metrics to `course_outputs/ablation_results.csv`. Use `--dry-run` to show the exact commands and hypotheses before committing GPU/CPU time.

Suggested report text: state each **hypothesis** before the table, then interpret whether results support it (not only “we got higher accuracy”).

## 5. Economic intuition: lift chart

`scripts/eval_lift_lstm.py` ranks test windows by **P(Massive Spike)** or **expected log-return**, buckets them into deciles, and plots **mean realized log-return** per decile. If higher deciles do not show higher mean returns, the model has little **ranking** value for a simple long strategy (before fees and execution).

## 6. Limitations to acknowledge in the write-up

- Steam markets are **non-stationary**; good backtest periods can fail after a major update or operation.
- **Fees (~15%)** mean small predicted edges disappear quickly.
- **MAPE** on returns is often huge near-zero denominators; prefer MAE on returns/log-returns or bucket metrics.
- **Item holdout** is harder but does not remove **temporal** correlation inside the train set; a stricter extension would be **purged** splits by date (not implemented here).

## 7. What we would try with more time

- Attention or Temporal Convolutional blocks instead of LSTM only.
- Explicit calibration (temperature scaling) on bucket probabilities.
- Plugging LSTM scores into `scripts/backtest.py` with the same fee and horizon as RF/GB.
- Rolling-origin evaluation (train on months 1–k, test month k+1).

## 8. Results table (fill in after you run experiments)

| Setting | Split | Test acc | Macro-F1 | Notes |
|---------|--------|----------|----------|--------|
| LSTM … | pooled |  |  |  |
| LSTM … | item_holdout |  |  |  |
| GB (buckets) | item_holdout |  |  | from `compare_lstm_vs_tabular.py` |

Keep the commands and seeds in an appendix so a grader can reproduce your numbers.
