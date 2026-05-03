"""
Weak 3-way sentiment labels (neg / neu / pos) for bootstrapping models.
Not ground truth — use for initial training or semi-supervised seeds.
"""

from __future__ import annotations

import re
from typing import Literal

Label = Literal["neg", "neu", "pos"]

_POS = frozenset(
    {
        "clutch",
        "insane",
        "god",
        "nice",
        "pog",
        "great",
        "beautiful",
        "clean",
        "legend",
        "carry",
        "hype",
        "win",
        "won",
        "destroyed",
        "destroying",
        "amazing",
        "well",
        "played",
        "good",
        "happy",
        "love",
        "beast",
    }
)
_NEG = frozenset(
    {
        "throw",
        "throwing",
        "choke",
        "choked",
        "bot",
        "bots",
        "trash",
        "disband",
        "awful",
        "terrible",
        "tilt",
        "tilted",
        "lose",
        "lost",
        "losing",
        "embarrassing",
        "disaster",
        "rip",
        "dead",
    }
)

_NEGATION = re.compile(
    r"\b(not|no|never|isnt|isn't|arent|aren't|dont|don't|wont|won't)\b"
)


def weak_sentiment_label(text: str) -> Label:
    from .preprocess import clean_text

    s = clean_text(text)
    if not s:
        return "neu"
    toks = s.split()
    pos_hits = sum(1 for t in toks if t in _POS)
    neg_hits = sum(1 for t in toks if t in _NEG)
    negated = bool(_NEGATION.search(s))

    if negated:
        pos_hits, neg_hits = neg_hits, pos_hits

    if pos_hits > neg_hits and pos_hits > 0:
        return "pos"
    if neg_hits > pos_hits and neg_hits > 0:
        return "neg"
    return "neu"


def label_to_id(name: Label) -> int:
    return {"neg": 0, "neu": 1, "pos": 2}[name]


def id_to_label(i: int) -> Label:
    return ("neg", "neu", "pos")[i]
