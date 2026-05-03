# NLP sentiment / momentum — full reproduction commands

Run from the repository root with Python environment containing `torch`, `scikit-learn`, `pandas`, `matplotlib`, `joblib`. Default database: `data/hltv_sentiment.db` (create via collector or `scripts/import_sample_multimatch.py` for a toy corpus).

1. `python scripts/migrate_hltv_sentiment_db.py`
2. `python scripts/train_sentiment_nb.py --split-mode by_match --ngram unigram --label-source weak`
3. `python scripts/train_sentiment_nb.py --split-mode by_match --ngram bigram --label-source weak --save-dir sentiment_models/nb_bigram`
4. `python scripts/train_sentiment_lstm.py --split-mode by_match --label-source weak --epochs 15 --patience 4`
5. `python scripts/train_sentiment_lstm.py --split-mode by_match --label-source weak --epochs 15 --patience 4 --hidden-dim 64 --save-dir sentiment_models/lstm_h64`
6. `python scripts/eval_sentiment.py --model-type nb --split-mode by_match --label-source weak`
7. `python scripts/eval_sentiment.py --model-type nb --split-mode by_match --label-source gold`
8. `python scripts/eval_sentiment.py --model-type lstm --checkpoint sentiment_models/lstm/lstm_weak.pt --split-mode by_match --label-source weak`
9. `python scripts/eval_sentiment.py --model-type lstm --checkpoint sentiment_models/lstm/lstm_weak.pt --split-mode by_match --label-source gold`
10. `python scripts/eval_sentiment.py --model-type lstm --checkpoint sentiment_models/lstm_h64/lstm_weak.pt --split-mode by_match --label-source weak --out-dir sentiment_eval/lstm_h64` (then copy/rename outputs if desired)
11. `python scripts/eval_sentiment_momentum.py --model-type nb --checkpoint sentiment_models/nb/nb_unigram.joblib --phase during --out nlp/ProjectDocs/momentum_report_nb.json`
12. `python scripts/eval_sentiment_momentum.py --model-type lstm --checkpoint sentiment_models/lstm/lstm_weak.pt --phase during --out nlp/ProjectDocs/momentum_report_lstm.json`
13. `python scripts/report_hltv_dataset_stats.py`
14. `python scripts/plot_momentum_report.py --input nlp/ProjectDocs/momentum_report_lstm.json --out-dir nlp/ProjectDocs/figures/momentum_lstm`
15. `python scripts/plot_match_velocity_exemplar.py --model-type nb --out nlp/ProjectDocs/figures/exemplar_match_velocity_nb.png`

**PDF report:** `pandoc nlp/ProjectDocs/FINAL_NLP_REPORT.md -o nlp/ProjectDocs/FINAL_NLP_REPORT.pdf --resource-path=nlp/ProjectDocs -V geometry:margin=1in`

See [`docs/HLTV_SENTIMENT_COLLECTION.md`](../docs/HLTV_SENTIMENT_COLLECTION.md) for legal constraints, robots.txt, and import paths.
