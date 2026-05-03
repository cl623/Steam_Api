# Verification checklist (report vs artifacts)

Use this with `FINAL_NLP_REPORT.md` open. **Pass** = value in report matches frozen JSON or source code behavior described.

## Abstract

| Claim | Where to verify |
|-------|-----------------|
| Corpus scale “2,174 comments across 16 matches” | `frozen_outputs/dataset_stats.json` → `n_comments`, `n_matches` |
| LSTM improves macro-F1 over unigram NB (weak, by_match) | `metrics/training_lstm_metrics.json` → `test.f1_macro` vs `metrics/training_nb_unigram_metrics.json` → `test.f1_macro` |
| Gold evaluation brittle on negative class | `metrics/eval_lstm_gold.json` + confusion PNGs in `figures/` |
| Lag correlations near zero | `frozen_outputs/momentum_report_lstm.json` → `aggregate_lag_pearson_mean`, `aggregate_lag_spearman_mean` |

## Section 5.1 Dataset table

| Row in table | JSON field |
|--------------|------------|
| Comments 2,174 | `dataset_stats.json` → `n_comments` |
| Matches 16 | `n_matches` |
| Gold-labeled 530 | `gold_labeled_comments` |
| Weak neg/neu/pos | `weak_label_counts.neg`, `.neu`, `.pos` |
| Non-null timestamps 100% | `posted_at_unix_nonnull_fraction` |
| Non-empty score_context 100% | `score_context_nonempty_fraction` |

Figures in section 5.1 should match the PNGs in `figures/dataset_*.png` (visual sanity check).

## Section 5.2 Classification

| Claim | Where to verify |
|-------|-----------------|
| Unigram NB test macro-F1 **0.606** | `training_nb_unigram_metrics.json` → `test.f1_macro` |
| Bigram NB test macro-F1 **0.596** | `training_nb_bigram_metrics.json` → `test.f1_macro` |
| LSTM test macro-F1 **0.658** | `training_lstm_metrics.json` → `test.f1_macro` |
| Gold NB macro-F1 **0.49**, n=101 | `eval_nb_gold.json` → `f1_macro`, `n_eval` |
| Gold LSTM macro-F1 **0.61**, n=101 | `eval_lstm_gold.json` → `f1_macro`, `n_eval` |
| Weak LSTM macro-F1 **0.658** (text also cites eval file) | `eval_lstm_weak.json` → `f1_macro` (should match training test eval on same split) |

Confusion matrices: compare `figures/confusion_*.png` to `confusion_matrix` arrays inside the eval JSONs if a pixel-level check is needed.

## Section 5.3 Momentum

| Claim | Where to verify |
|-------|-----------------|
| “5 matches” analyzed (during phase) | `momentum_report_lstm.json` → `n_matches_analyzed` |
| Mean lag correlations small / mixed sign | `aggregate_lag_pearson_mean`, `aggregate_lag_spearman_mean` |
| LSTM momentum figures | `figures/momentum_lstm/*.png` vs JSON aggregates (plots are derived from same JSON) |

**Swing proxy definition:** `methodology_source/nlp/velocity.py` → `swing_labels_from_context`, `parse_round_differential`.

**Velocity bins:** `velocity_per_bin` in the same file; default bin list in `methodology_source/scripts/eval_sentiment_momentum.py` (CLI defaults).

## Section 3 (methodology accuracy)

| Claim | Source file in `methodology_source/` |
|-------|--------------------------------------|
| `by_match` split, 15% val/test | `nlp/dataset.py` → `train_val_test_split` |
| LSTM is per-comment tokens, not cross-comment RNN | `nlp/models_lstm.py` → `CommentLSTM.forward` |
| Weak labels / gold / hybrid | `nlp/dataset.py` → `apply_label_source` |
| Phases pre/during/post | `nlp/time_windows.py` |
| `scores_from_probs` in [-1,1] | `nlp/velocity.py` |

## Section 2 (references)

| Claim | Verify |
|-------|--------|
| Five papers with venues/years | `references.bib` + report section 2 prose |

## Optional: full reproduction

If the verifier has the repo + DB: run the numbered commands in report section 4; outputs should match these JSONs when the database is identical.
