"""Pickle-stable analyzer for sklearn CountVectorizer."""

from __future__ import annotations

from .preprocess import tokenize_simple


def count_vectorizer_analyzer_unigram(doc: str) -> list[str]:
    return tokenize_simple(doc)


def count_vectorizer_analyzer_bigram(doc: str) -> list[str]:
    """Unigrams plus adjacent bigrams (sklearn ignores ngram_range with a callable analyzer)."""
    toks = tokenize_simple(doc)
    if len(toks) < 2:
        return toks
    bigrams = [f"{toks[i]} {toks[i + 1]}" for i in range(len(toks) - 1)]
    return toks + bigrams


def count_vectorizer_analyzer(doc: str) -> list[str]:
    """Default: unigram only (backward compatible)."""
    return count_vectorizer_analyzer_unigram(doc)
