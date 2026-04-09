# Sample multimatch dataset (synthetic)

Files here support local testing of the sentiment pipeline without live HLTV access.

| File | Purpose |
|------|---------|
| `hltv_comments_multimatch.jsonl` | 5 matches × 12 comments; timestamps and `score_context` scorelines |
| `gold_labels_example.csv` | Hand-style labels for a subset (30 rows) for `--label-source gold` / hybrid eval |

Regenerate (overwrites):

```bash
python scripts/build_sample_multimatch_dataset.py
```

Import into `data/hltv_sentiment.db`:

```bash
python scripts/import_sample_multimatch.py
# skip gold: python scripts/import_sample_multimatch.py --skip-gold-csv
```

Text is **synthetic** (template phrases). Use real exports for research claims.
