# Verification checklist — report v2 (`feature/nlp-report-v2`)

Review input: [`../Verification_Version1.md`](../Verification_Version1.md). Canonical report: [`FINAL_NLP_REPORT.md`](FINAL_NLP_REPORT.md).

## Abstract and title

| Claim | Verify |
|-------|--------|
| Conservative framing (evaluate, not predict strong momentum) | Read abstract + title against `momentum_report_lstm.json` aggregates |
| “2,174 comments”, “16 matches” | `frozen_outputs/dataset_stats.json` |
| Second LSTM (hidden 64) mentioned | `metrics/training_lstm_h64_metrics.json` exists; `metrics/eval_lstm_h64_weak.json` |

## Section 5.1 dataset

| Table row | `frozen_outputs/dataset_stats.json` keys |
|-----------|-------------------------------------------|
| Comment/match counts, gold count, weak counts | `n_comments`, `n_matches`, `gold_labeled_comments`, `weak_label_counts` |

## Section 5.2 classification table (weak test, n=390)

| Row | Primary source |
|-----|------------------|
| NB unigram row | `metrics/training_nb_unigram_metrics.json` → `test.report` (or `eval_nb_weak.json` — should match) |
| NB bigram | `metrics/training_nb_bigram_metrics.json` → `test.f1_macro` and per-class from `test.report` |
| LSTM hidden 128 | `metrics/training_lstm_metrics.json` + `metrics/eval_lstm_weak.json` |
| LSTM hidden 64 | `metrics/training_lstm_h64_metrics.json` + `metrics/eval_lstm_h64_weak.json` |

**Gold n=101 discussion:** `metrics/eval_lstm_gold.json` vs `metrics/eval_lstm_h64_gold.json` (`f1_macro`, confusion on class neg).

## Section 5.3 momentum

| Claim | `frozen_outputs/momentum_report_lstm.json` |
|-------|-----------------------------------------------|
| Five matches | `n_matches_analyzed` |
| Near-zero lag means | `aggregate_lag_pearson_mean`, `aggregate_lag_spearman_mean` |

## Related work venues

All five numbered references in the report should map to **ACL or EMNLP** PDFs in [`references.bib`](references.bib) (no SIGDIAL/NLP4DH in v2).

## Methodology vs code

| Report statement | File under `methodology_source/` |
|------------------|----------------------------------|
| Swing proxy | `nlp/velocity.py` |
| Splits | `nlp/dataset.py` |
| LSTM per-comment | `nlp/models_lstm.py` |
| Momentum CLI | `scripts/eval_sentiment_momentum.py` |

## Full reproduction

[`../REPRO_COMMANDS.md`](../REPRO_COMMANDS.md) (copy in this bundle if present as `REPRO_COMMANDS.md`).
