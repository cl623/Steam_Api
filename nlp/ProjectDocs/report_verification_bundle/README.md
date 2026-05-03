# Report verification bundle

This folder is a **self-contained snapshot** for a second reviewer (human or LLM) to check [`FINAL_NLP_REPORT.md`](FINAL_NLP_REPORT.md) for factual consistency, metric accuracy, and alignment with the implemented methodology.

## Contents

| Path | Purpose |
|------|--------|
| `FINAL_NLP_REPORT.md` / `.pdf` | The report under review (Markdown is authoritative for diffs; PDF for layout). |
| `references.bib` | Bibliography entries cited in the report. |
| `frozen_outputs/` | JSON written by the same pipeline the report describes (`dataset_stats.json`, `momentum_report_*.json`). |
| `metrics/eval_*.json` | Copies of `sentiment_eval/metrics_*.json` from classification evaluation (includes `eval_lstm_h64_*` for the v2 LSTM ablation). |
| `metrics/training_*.json` | Copies of `sentiment_models/**/_metrics.json` (includes `training_lstm_h64_metrics.json`). |
| `REPRO_COMMANDS.md` | Full shell runbook copied from [`../REPRO_COMMANDS.md`](../REPRO_COMMANDS.md). |
| `Verification_Version1.md` | External review notes that drove report v2 edits. |
| `Verification_Version2.md` | Layout + classification P/R checklist (v2.1). |
| `methodology_source/` | Copies of `nlp/*.py` and `scripts/*sentiment*.py` (and stats script) that define labels, splits, models, velocity, and momentum evaluation. |
| `figures/` | Copies of PNGs embedded in the report (confusion matrices, dataset exploration, momentum plots, exemplar). |
| `docs_HLTV_SENTIMENT_COLLECTION.md` | Copy of repo `docs/HLTV_SENTIMENT_COLLECTION.md` for ingest/ethics/commands cross-check against section 3.1. |
| `course_ProjectGuidelines.txt` | Copy of course final-project instructions (structure, related-work expectations). |
| `VERIFICATION_CHECKLIST.md` | Claim-by-claim map from the report to JSON keys and source files. |

## How to verify

1. Open `VERIFICATION_CHECKLIST.md` and work top to bottom.
2. For every numeric claim in section 5 of the report, open the corresponding JSON in `frozen_outputs/` or `metrics/` and confirm the value matches (allowing rounding in prose).
3. For methodology claims (splits, swing proxy, LSTM scope), grep or read the matching file under `methodology_source/`.
4. Cross-check reference titles/years/venues against `references.bib` and the in-text URLs in section 2.

## Limitations

- **Database not included:** `data/hltv_sentiment.db` may be large, gitignored, or sensitive; this bundle assumes metrics JSON reflects the corpus the author used. To fully re-run experiments, clone the repo and follow `REPRO_COMMANDS.md`.
- **Checkpoint weights not included:** trained `.joblib` / `.pt` files are omitted to save space; retraining reproduces metrics if the DB is unchanged.

## Bundle version

**v2** (`feature/nlp-report-v2`): ACL/EMNLP-only related work, LSTM hidden-size ablation, shortened main report with commands externalized to `REPRO_COMMANDS.md`. **v2.1:** §5.2 precision/recall tables, §5.3 figure placement + scaled width, LaTeX `placeins` / `\FloatBarrier` before references, Pandoc `-f markdown+yaml_metadata_block+raw_attribute`. Paths inside `methodology_source/` preserve original module layout (`nlp/...`, `scripts/...`) for clarity.
