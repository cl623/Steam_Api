"""
Gaming-flavoured text normalization for CS2 / Twitch-style chat.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List

# URLs, @handles, Steam-style IDs
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
_HANDLE_RE = re.compile(r"@\w+|/\w{3,}/", re.I)
_STEAM_ID_RE = re.compile(r"STEAM_[\d:]+", re.I)

# Common emoticon / kaomoji noise (conservative)
_EMOTI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]+|"
    r"[:;=8][\-^']?[)(/\\|pPDO]+|"
    r"[)(/\\|]+[\-^']?[:;=8]",
    re.UNICODE,
)

# Repeated punctuation / elongation
_ELONG_RE = re.compile(r"(.)\1{3,}")

_SLANG_REPLACE = {
    "nt": "nice try",
    "wp": "well played",
    "gg": "good game",
    "ggs": "good game",
    "ez": "easy",
    "eco": "economy round",
    "force": "force buy",
    "tilt": "tilted",
    "pog": "excited",
    "poggers": "excited",
    "lul": "laugh",
    "kek": "laugh",
}


def clean_text(text: str, *, lowercase: bool = True) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text))
    s = _URL_RE.sub(" ", s)
    s = _HANDLE_RE.sub(" ", s)
    s = _STEAM_ID_RE.sub(" ", s)
    s = _EMOTI_RE.sub(" ", s)
    s = re.sub(r"[^\w\s'\-]", " ", s, flags=re.UNICODE)
    s = _ELONG_RE.sub(r"\1\1\1", s)
    tokens = s.lower().split() if lowercase else s.split()
    out: List[str] = []
    for t in tokens:
        key = t.lower().strip("'") if lowercase else t.strip("'")
        if key in _SLANG_REPLACE:
            out.extend(_SLANG_REPLACE[key].split())
        else:
            out.append(t.lower() if lowercase else t)
    s = " ".join(out)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokenize_simple(text: str) -> List[str]:
    return [t for t in clean_text(text).split() if t]
