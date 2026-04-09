"""Pickle-stable analyzer for sklearn CountVectorizer."""

from __future__ import annotations

from .preprocess import tokenize_simple


def count_vectorizer_analyzer(doc: str) -> list[str]:
    return tokenize_simple(doc)
