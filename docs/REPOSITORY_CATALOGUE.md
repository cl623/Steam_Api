# Repository File Catalogue

This catalogue classifies project files by purpose and **visibility** for remote repository management.

| Badge | Meaning |
|-------|---------|
| **PUBLIC** | Safe to publish on the main remote (`cl623/Steam_Api`) for forks and contributors |
| **COURSE_REPO** | Belongs in the course handoff repo ([DS677_CourseProject](https://github.com/cl623/DS677_CourseProject)) |
| **LOCAL** | Keep on disk locally; do not track on the main public remote |

Course submission materials (reports, verification bundles, roadmaps) stay **LOCAL** on the main repo and are mirrored in **COURSE_REPO** where appropriate.

---

## Category definitions

| Category | Purpose |
|----------|---------|
| **Web Application Code** | Flask UI, routes, templates, static assets |
| **Data Collection Code** | Steam market and HLTV ingestion |
| **Machine Learning Code** | Tabular RF/GB price prediction |
| **Deep Learning Code** | PyTorch LSTM sequence pipeline |
| **NLP Code** | HLTV sentiment, velocity, time windows |
| **Main Scripts** | Primary CLIs for production workflows |
| **Course / Research Scripts** | DS677 experiments and ablations |
| **Tests and Fixtures** | Pytest and HTML fixtures |
| **Sample Data (Development)** | Small synthetic datasets for local NLP tests |
| **Runtime Data** | SQLite DBs, logs (gitignored) |
| **Model Artifacts** | Checkpoints and joblib outputs (gitignored) |
| **Public Documentation** | Fork-friendly setup and usage guides |
| **Coursework Documentation** | Reports, grading bundles, repro snapshots |
| **Summary Documents** | Model and project summaries (split by visibility) |
| **Roadmaps** | Version milestones and DL phase plans |
| **Internal Engineering Analysis** | Deep dives, reviews, autopsies |
| **Agent Specification Documents** | Cursor rules/skills (outside this repo) |
| **Project Configuration** | Dependencies, git policy, README |

---

## Directory inventory

### Root

| Path | Category | Visibility |
|------|----------|------------|
| `run.py` | Main Scripts | PUBLIC |
| `app/` | Web Application Code | PUBLIC |
| `README.md` | Public Documentation | PUBLIC |
| `MIGRATION_NOTES.md` | Public Documentation | PUBLIC |
| `requirements_python.txt` | Project Configuration | PUBLIC |
| `dependencies.txt` | Project Configuration | PUBLIC |
| `Requirements.txt` | Project Configuration | LOCAL (legacy v1 checklist, not pip pins) |
| `Price History.txt` | Internal Engineering Analysis | LOCAL |
| `app.py`, `batch_processor.py` | Legacy code | LOCAL (prefer `app/` + `run.py`) |
| `LICENSE` | Project Configuration | PUBLIC |

### `app/`, `templates/`, `static/`

| Path | Category | Visibility |
|------|----------|------------|
| `app/*.py` | Web Application Code | PUBLIC |
| `templates/*.html` | Web Application Code | PUBLIC |
| `static/css/style.css` | Web Application Code | PUBLIC |

### `collector/`

| Path | Category | Visibility |
|------|----------|------------|
| `collector/market_collector.py` | Data Collection Code | PUBLIC |
| `collector/hltv_comments.py` | HLTV Collection Code | PUBLIC |

### `ml/`

| Path | Category | Visibility |
|------|----------|------------|
| `ml/price_predictor.py` | Machine Learning Code | PUBLIC |
| `ml/feature_extractor.py` | Machine Learning Code | PUBLIC |
| `ml/model_comparison.py` | Machine Learning Code | PUBLIC |
| `ml/model_diagnostics.py` | Machine Learning Code | PUBLIC |
| `ml/cs2_event_features.py` | Machine Learning Code | PUBLIC |
| `ml/deep_learning/` | Deep Learning Code | PUBLIC (main) + **COURSE_REPO** (handoff copy) |

### `nlp/`

| Path | Category | Visibility |
|------|----------|------------|
| `nlp/*.py` (runtime modules) | NLP Code | PUBLIC |
| `nlp/ProjectDocs/` | Coursework Documentation | **LOCAL** |

### `scripts/`

| Path | Category | Visibility |
|------|----------|------------|
| `run_collector.py`, `migrate_db.py`, `migrate_ml_schema.py` | Main Scripts | PUBLIC |
| `train_model.py`, `evaluate_model.py`, `backtest.py` | Main Scripts | PUBLIC |
| `run_comparison_with_plots.py`, `analyze_predictions.py` | Main Scripts | PUBLIC |
| `test_cookies.py`, `import_cookies.py`, `check_duplicates.py` | Main Scripts | PUBLIC |
| `run_hltv_comment_collector.py`, `migrate_hltv_sentiment_db.py` | Course / Research Scripts | PUBLIC |
| `train_sentiment_nb.py`, `train_sentiment_lstm.py` | Course / Research Scripts | PUBLIC |
| `eval_sentiment.py`, `eval_sentiment_momentum.py` | Course / Research Scripts | PUBLIC |
| `train_lstm.py`, `validate_dl_pipeline.py` | Course / Research Scripts | PUBLIC + **COURSE_REPO** |
| `compare_lstm_vs_tabular.py`, `eval_lift_lstm.py`, `run_course_ablations.py` | Course / Research Scripts | PUBLIC + **COURSE_REPO** |
| `build_sample_multimatch_dataset.py`, `import_sample_multimatch.py` | Sample Data tooling | PUBLIC |

### `tests/`, `samples/`, `.github/`

| Path | Category | Visibility |
|------|----------|------------|
| `tests/` | Tests and Fixtures | PUBLIC |
| `samples/` | Sample Data (Development) | PUBLIC |
| `.github/workflows/nlp-tests.yml` | Tests and Fixtures | PUBLIC |

### `docs/` (public subset)

| File | Category | Visibility |
|------|----------|------------|
| `USER_GUIDE.md` | Public Documentation | PUBLIC |
| `WORKFLOW_SUMMARY.md` | Public Documentation | PUBLIC |
| `COOKIE_SETUP_GUIDE.md` | Public Documentation | PUBLIC |
| `ML_SCRIPTS_AND_FEATURES.md` | Public Documentation | PUBLIC |
| `TRAINING_PROCESS.md` | Public Documentation | PUBLIC |
| `TRAINING_AND_PAUSE_SUMMARY.md` | Public Documentation | PUBLIC |
| `PAUSE_FUNCTIONALITY.md` | Public Documentation | PUBLIC |
| `HLTV_SENTIMENT_COLLECTION.md` | Public Documentation | PUBLIC |
| `HLTV_Match_ResultsCS2_DATASET.md` | Public Documentation | PUBLIC |
| `DATABASE_SCHEMA_ML_REVIEW.md` | Public Documentation | PUBLIC |
| `ML_SCHEMA_OPTIMIZATION_SUMMARY.md` | Public Documentation | PUBLIC |
| `MODEL_SUMMARY.md` | Summary Documents | PUBLIC (+ copy in **COURSE_REPO**) |
| `REPOSITORY_CATALOGUE.md` | Project Configuration | PUBLIC |
| `PUBLIC_DOCS_INDEX.md` | Project Configuration | PUBLIC |

### `docs/` (local-only)

| File | Category | Visibility |
|------|----------|------------|
| `COURSE_EVALUATION.md` | Coursework Documentation | **LOCAL** |
| `COURSE_PROJECT_PROGRESS.md` | Coursework Documentation | **LOCAL** + **COURSE_REPO** |
| `PROJECT_SUMMARY_BEFORE_COURSE_PROJECT.md` | Coursework Documentation | **LOCAL** |
| `FINAL_PROJECT_REPORT.md` | Coursework Documentation | **LOCAL** |
| `VERSION2.0.md` … `VERSION3.0.md`, `VERSION2.5_ROADMAP.md` | Roadmaps | **LOCAL** |
| `DEEP_LEARNING_*.txt` | Roadmaps | **LOCAL** |
| `BACKTEST_RESULTS.md` | Internal Engineering Analysis | **LOCAL** |
| `PREDICTION_ACCURACY_ANALYSIS.md` | Internal Engineering Analysis | **LOCAL** |
| `MOVING_AVERAGES_DEEP_DIVE.md` | Internal Engineering Analysis | **LOCAL** |
| `LOOKBACK_DAYS_ANALYSIS.md` | Internal Engineering Analysis | **LOCAL** |
| `CODE_REVIEW.md` | Internal Engineering Analysis | **LOCAL** |
| `COLLECTOR_READINESS_REVIEW.md` | Internal Engineering Analysis | **LOCAL** |
| `DATABASE_COLLECTION_REVIEW.md` | Internal Engineering Analysis | **LOCAL** |
| `DATA_COLLECTION_IMPROVEMENTS.md` | Internal Engineering Analysis | **LOCAL** |
| `IMPROVEMENTS_IMPLEMENTED.md` | Internal Engineering Analysis | **LOCAL** |
| `WORKER_BALANCE_ANALYSIS.md` | Internal Engineering Analysis | **LOCAL** |
| `THREADING_ANALYSIS.md` | Internal Engineering Analysis | **LOCAL** |
| `STEAM_RATE_LIMIT_ANALYSIS.md` | Internal Engineering Analysis | **LOCAL** |
| `MODEL_IMPROVEMENTS.md` | Internal Engineering Analysis | **LOCAL** |
| `MODEL_TRAINING_PARAMETERS.md` | Internal Engineering Analysis | **LOCAL** |
| `Project Proposal_*.pdf`, `docs/*.pdf` | Coursework Documentation | **LOCAL** |

### Gitignored runtime paths (reference)

| Path | Category | Visibility |
|------|----------|------------|
| `data/` | Runtime Data | LOCAL |
| `models/`, `models_*/` | Model Artifacts | LOCAL |
| `course_outputs/`, `course_eval/` | Model Artifacts | LOCAL |
| `sentiment_eval/`, `sentiment_models/` | Model Artifacts | LOCAL |
| `comparison_output/`, `backtest_output/` | Model Artifacts | LOCAL |
| `HLTV/` (raw scrape dumps) | Runtime Data | LOCAL |

### Agent specification (out of repo)

| Location | Category | Visibility |
|----------|----------|------------|
| `~/.cursor/rules/`, skills, AGENTS.md in other workspaces | Agent Specification Documents | **LOCAL** (never in main remote) |

---

## Remote management policy

### Main remote (`cl623/Steam_Api`)

Publish: application code, ML/DL/NLP runtime code, production and research scripts, tests, samples, and **public documentation** listed above.

Do **not** publish: `nlp/ProjectDocs/`, course reports, roadmaps, internal analysis docs, PDFs, or agent alignment files.

### Course repo (`cl623/DS677_CourseProject`)

Publish: `ml/deep_learning/`, core course scripts, minimal course docs (`COURSE_PROJECT_PROGRESS.md`, `COURSE_EVALUATION.md`, `MODEL_SUMMARY.md`), and a learning-focused README.

### Sync rule

When course docs change locally, copy updates into the DS677 repo and push there. The main repo keeps code open; narrative coursework stays local.

---

## Maintainer checklist (pre-push)

- [ ] `git status` shows no staged paths under `nlp/ProjectDocs/`
- [ ] No `docs/COURSE_*`, `docs/VERSION*`, `docs/FINAL_*`, or `docs/*.pdf` staged
- [ ] No internal `*_ANALYSIS.md`, `*_REVIEW.md`, or `BACKTEST_RESULTS.md` staged
- [ ] `docs/PUBLIC_DOCS_INDEX.md` still lists only public docs
- [ ] Course-only changes go to DS677_CourseProject when intended for the professor

Quick check:

```bash
git diff --cached --name-only | findstr /I "ProjectDocs COURSE VERSION FINAL BACKTEST ANALYSIS REVIEW ROADMAP .pdf"
```

(empty output = safe for main remote doc policy)
