# Course project progress: deep learning phase

The **course project** is defined here as the work that begins with **Version 3.0 deep learning**: moving from **tabular return regression** to a **PyTorch LSTM** pipeline, with reporting-focused **evaluation** and **reproducibility** tooling.

The **baseline system** (Flask app, collector, RF/GB, backtest) is summarized in [PROJECT_SUMMARY_BEFORE_COURSE_PROJECT.md](PROJECT_SUMMARY_BEFORE_COURSE_PROJECT.md).

---

## 1. Motivation (from the V3 roadmap)

- Tabular RF/GB had hit practical limits on **temporal memory** and **extreme returns** (see **VERSION3.0.md**).
- The course direction: **sliding-window sequences**, **log-return** targets, **fee-aware buckets**, optional **forward-looking countdown** features in the temporal tensor, and losses that can emphasize **rare upside** (class weights / focal loss).

---

## 2. Code added: `ml/deep_learning/`

| Component | Role |
|-----------|------|
| **`dataset.py`** | Load SQLite price history; build **per-item** sliding windows `(seq_len × temporal features)`; merge **`cs2_event_daily`** (including **days_until_*** countdowns); **static** item vector from `ItemFeatureExtractor`; **`build_dataloaders`** with **`SequenceNormalizer`** (min–max by default). |
| **`buckets.py`** | Four **log-return** buckets (large drop, flat, break-even, massive spike); helpers to map returns ↔ buckets; **expected log-return from softmax** for scalar metrics. |
| **`model.py`** | **`SteamMarketLSTM`**: LSTM encoder + concat static features + MLP head → **4-class logits**; checkpoint save/load. |
| **`losses.py`** | Class-weighted CE, **FocalLoss**, optional asymmetric regression loss. |
| **`normalization.py`** | Fit-on-train, apply to val/test/inference; **persisted** as `normalizer.npz`. |
| **`__init__.py`** | Public exports for training and evaluation scripts. |

---

## 3. Training and validation scripts

| Script | Purpose |
|--------|---------|
| **`scripts/train_lstm.py`** | End-to-end training: argparse for `seq_len`, `max_items`, **split mode** (`pooled` vs **`item_holdout`**), holdout fraction/seed, loss (`ce` / `weighted-ce` / `focal`), early stopping; logs **accuracy** and **macro-F1**; writes **`best_model.pt`**, **`last_model.pt`**, **`normalizer.npz`**, **`split_meta.json`**. |
| **`scripts/validate_dl_pipeline.py`** | Smoke-test: shapes, normalizer stats, one batch from DataLoaders (no training). |

**Example report-oriented run** (item holdout, focal loss, saved under `models_lstm_report/`):

```bash
python scripts/train_lstm.py --max-items 50 --epochs 20 --split-mode item_holdout \
  --holdout-fraction 0.2 --holdout-seed 42 --loss focal --spike-boost 2.0 \
  --save-dir models_lstm_report --patience 6
```

---

## 4. Fair comparison vs tabular baselines

| Script | Purpose |
|--------|---------|
| **`scripts/compare_lstm_vs_tabular.py`** | Rebuilds the **same item-level holdout** as the LSTM; trains **RF** and **GB** on tabular rows for **train items only**; evaluates on **test items** with **bucket accuracy**, **macro-F1**, and **MAE in log-return space**; optional **`--lstm-checkpoint`** loads the trained LSTM using the **saved normalizer** beside the checkpoint. |

**Important caveat (documented in script output):** tabular **daily rows** and LSTM **windows** are not aligned sample-by-sample; metrics are comparable at the level of **same held-out item names** and **same bucket definitions**.

---

## 5. Reporting and pedagogy

| Artifact | Purpose |
|----------|---------|
| **`docs/COURSE_EVALUATION.md`** | Explains **window correlation**, **pooled vs item holdout**, how to compare LSTM vs GB/RF, ablations, lift charts, limitations, and a **template results table** for the write-up. |
| **`scripts/eval_lift_lstm.py`** | **Decile lift**: rank test windows by **P(spike)** or **expected log-return**; plot mean realized log-return per decile (default output under `course_eval/`). |
| **`scripts/run_course_ablations.py`** | Runs a **small grid** of short trainings (pooled vs holdout, `seq_len`, etc.); appends metrics to **`course_outputs/ablation_results.csv`**; **`--dry-run`** prints commands and hypotheses. |

Repository hygiene: **`.gitignore`** entries for **`course_outputs/`** and **`course_eval/`** so experiment artifacts stay local unless you choose to commit them.

---

## 6. Supporting repo updates

- **`requirements_python.txt`**: Python dependencies for the DL stack (e.g. **PyTorch**) alongside the rest of the project.
- **`docs/MODEL_SUMMARY.md`**, **`docs/VERSION3.0.md`**: Written context for **tabular benchmark numbers** and the **V3 transition plan**; cite these when contrasting “before” and “during” the course project.
- **`scripts/validate_dl_pipeline.py`** and **`ml/deep_learning/__init__.py`** kept in sync with **`build_dataloaders`** returning split **metadata**.

---

## 7. Empirical snapshot (example, not committed to the repo)

A full training run on **50 items** with **item holdout** (40 train / 10 test items) and **focal loss** produced (on **49,545** test windows): **~56% bucket accuracy**, **macro-F1 ≈ 0.49**, with per-class behavior documented in the training log. A subsequent **`compare_lstm_vs_tabular.py`** run on the **same holdout** showed **GB** and **RF** **higher** on bucket accuracy and macro-F1 than this LSTM on that split—useful honestly in the report as “strong tabular baseline vs sequence model under strict generalization.” **Re-run** the scripts on your machine to refresh numbers for your final document.

---

## 8. Suggested “what we did” checklist for the report

1. Defined **four buckets** in log-return space aligned with **fees**.  
2. Built **3D** sequence data + **static** fusion + **normalization**.  
3. Trained **LSTM** with **pooled** and/or **item holdout** splits.  
4. Compared to **RF/GB** with **aligned bucket metrics** + **MAE(log-return)**.  
5. Optional: **lift chart** and **ablation CSV**; **`COURSE_EVALUATION.md`** for limitations text.  
6. Acknowledged **non-stationarity**, **overlap** between sliding windows, and **backtest** still **tabular-only** if you did not extend `backtest.py` to the LSTM.

---

## 9. Natural next steps (if extending the course project)

- Wire **LSTM scores** into **`scripts/backtest.py`** (same fee/horizon as RF/GB).  
- Rolling **time-based** validation in addition to item holdout.  
- Calibration of bucket **probabilities** (e.g. temperature scaling).
