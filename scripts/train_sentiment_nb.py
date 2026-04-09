#!/usr/bin/env python
"""Train sklearn MultinomialNB sentiment baselines (weak labels from nlp.weak_labels)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from nlp.dataset import (  # noqa: E402
    add_weak_labels,
    apply_label_source,
    default_db_path,
    load_comments_dataframe,
    split_meta_dict,
    train_val_test_split,
)

logger = logging.getLogger("train_sentiment_nb")


def build_pipeline(
    ngram: str, max_features: int, class_prior: np.ndarray | None = None
) -> Pipeline:
    from nlp.vectorizer_utils import (
        count_vectorizer_analyzer_bigram,
        count_vectorizer_analyzer_unigram,
    )

    if ngram == "unigram":
        analyzer = count_vectorizer_analyzer_unigram
    elif ngram == "bigram":
        analyzer = count_vectorizer_analyzer_bigram
    else:
        raise ValueError("ngram must be unigram or bigram")
    return Pipeline(
        [
            (
                "vec",
                CountVectorizer(
                    analyzer=analyzer,
                    min_df=1,
                    max_features=max_features,
                ),
            ),
            (
                "clf",
                MultinomialNB(
                    class_prior=class_prior,
                    fit_prior=False if class_prior is not None else True,
                ),
            ),
        ]
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--ngram", choices=("unigram", "bigram"), default="unigram")
    ap.add_argument("--split-mode", choices=("random", "by_match", "by_time"), default="by_match")
    ap.add_argument("--val-fraction", type=float, default=0.15)
    ap.add_argument("--test-fraction", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--max-features", type=int, default=50_000)
    ap.add_argument(
        "--save-dir",
        type=Path,
        default=PROJECT_ROOT / "sentiment_models" / "nb",
    )
    ap.add_argument(
        "--label-source",
        choices=("weak", "gold", "hybrid"),
        default="weak",
        help="weak=lexicon; gold=only hand-labeled rows; hybrid=gold else weak",
    )
    ap.add_argument(
        "--use-pre-match-prior",
        action="store_true",
        help="Estimate NB class prior from pre-match comments in train split.",
    )
    args = ap.parse_args()

    db_path = args.db or default_db_path()
    if not db_path.is_file():
        logger.error("Database not found: %s — run collector first.", db_path)
        return 1

    raw = load_comments_dataframe(db_path, limit=args.limit)
    if raw.empty:
        logger.error("No comments in DB.")
        return 1
    df = add_weak_labels(raw)
    tr, va, te = train_val_test_split(
        df,
        mode=args.split_mode,
        val_fraction=args.val_fraction,
        test_fraction=args.test_fraction,
        random_state=args.seed,
    )
    tr_f = apply_label_source(tr, args.label_source)
    if tr_f.empty:
        logger.error(
            "Train split empty after label-source=%s — add gold labels or use weak/hybrid.",
            args.label_source,
        )
        return 1

    class_prior = None
    if args.use_pre_match_prior:
        if "comment_phase" in tr.columns:
            pre = tr[tr["comment_phase"] == "pre"].copy()
        else:
            pre = tr.iloc[:0].copy()
        pre_f = apply_label_source(pre, args.label_source) if not pre.empty else pre
        if not pre_f.empty:
            y_pre = pre_f["label"].to_numpy().astype(int)
            counts = np.bincount(y_pre, minlength=3).astype(float)
            if counts.sum() > 0:
                class_prior = counts / counts.sum()
        if class_prior is None:
            logger.warning(
                "No usable pre-match rows for class prior; falling back to fit_prior=True"
            )

    pipe = build_pipeline(args.ngram, args.max_features, class_prior=class_prior)
    x_tr, y_tr = tr_f["raw_text"].astype(str), tr_f["label"].to_numpy()
    pipe.fit(x_tr, y_tr)

    def eval_split(name: str, part) -> dict:
        if part.empty:
            return {"n": 0}
        pf = apply_label_source(part, args.label_source)
        if pf.empty:
            return {"n": 0, "note": f"no rows for label_source={args.label_source}"}
        y_true = pf["label"].to_numpy()
        y_pred = pipe.predict(pf["raw_text"].astype(str))
        return {
            "n": int(len(pf)),
            "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
            "f1_micro": float(f1_score(y_true, y_pred, average="micro", zero_division=0)),
            "confusion_matrix": confusion_matrix(y_true, y_pred, labels=[0, 1, 2]).tolist(),
            "report": classification_report(
                y_true, y_pred, labels=[0, 1, 2], target_names=["neg", "neu", "pos"], zero_division=0
            ),
        }

    metrics = {
        "train": eval_split("train", tr),
        "val": eval_split("val", va),
        "test": eval_split("test", te),
        "split": split_meta_dict(
            args.split_mode,
            args.val_fraction,
            args.test_fraction,
            args.seed,
            len(tr),
            len(va),
            len(te),
        ),
        "ngram": args.ngram,
        "label_source": args.label_source,
        "use_pre_match_prior": bool(args.use_pre_match_prior),
        "pre_match_class_prior": class_prior.tolist() if class_prior is not None else None,
    }

    args.save_dir.mkdir(parents=True, exist_ok=True)
    model_path = args.save_dir / f"nb_{args.ngram}.joblib"
    joblib.dump(pipe, model_path)
    meta_path = args.save_dir / f"nb_{args.ngram}_metrics.json"
    meta_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    logger.info("Saved model %s", model_path)
    logger.info("Metrics written %s", meta_path)
    print(metrics["test"].get("report", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
