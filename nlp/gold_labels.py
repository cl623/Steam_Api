"""Parse hand-label tokens from CSV or spreadsheets."""

from __future__ import annotations


def parse_gold_label_cell(value) -> int:
    """
    Map cell to 0/1/2. Accepts integers, neg/neu/pos, common aliases.
    """
    if value is None or (isinstance(value, float) and str(value) == "nan"):
        raise ValueError("empty gold label")
    if isinstance(value, bool):
        raise ValueError("invalid gold label type")
    if isinstance(value, (int, float)):
        i = int(value)
        if i in (0, 1, 2):
            return i
        raise ValueError(f"gold label must be 0,1,2 not {value}")
    s = str(value).strip().lower()
    if s in ("0", "neg", "negative", "n"):
        return 0
    if s in ("1", "neu", "neutral", "u"):
        return 1
    if s in ("2", "pos", "positive", "p"):
        return 2
    raise ValueError(f"Unrecognized gold label: {value!r}")
