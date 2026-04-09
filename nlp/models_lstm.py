"""Small Embedding + LSTM classifier for comment sequences."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn


class CommentLSTM(nn.Module):
    def __init__(
        self,
        vocab_size: int,
        embed_dim: int = 128,
        hidden_dim: int = 128,
        num_classes: int = 3,
        padding_idx: int = 0,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.padding_idx = padding_idx
        self.embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=padding_idx)
        self.dropout = nn.Dropout(dropout)
        self.lstm = nn.LSTM(
            embed_dim,
            hidden_dim,
            batch_first=True,
            num_layers=1,
        )
        self.fc = nn.Linear(hidden_dim, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq)
        emb = self.dropout(self.embedding(x))
        out, _ = self.lstm(emb)
        mask = (x != self.padding_idx).float().unsqueeze(-1)
        summed = (out * mask).sum(dim=1)
        denom = mask.sum(dim=1).clamp(min=1.0)
        pooled = summed / denom
        return self.fc(pooled)


def build_vocab(
    texts: List[str],
    *,
    min_freq: int = 1,
    max_tokens: int = 50_000,
) -> Tuple[Dict[str, int], List[str]]:
    from collections import Counter

    from .preprocess import tokenize_simple

    counts: Counter[str] = Counter()
    for t in texts:
        counts.update(tokenize_simple(t))
    pairs = [(w, c) for w, c in counts.items() if c >= min_freq]
    pairs.sort(key=lambda x: (-x[1], x[0]))
    pairs = pairs[: max_tokens - 2]
    stoi: Dict[str, int] = {"<pad>": 0, "<unk>": 1}
    itos: List[str] = ["<pad>", "<unk>"]
    for w, _ in pairs:
        if w in stoi:
            continue
        stoi[w] = len(itos)
        itos.append(w)
    return stoi, itos


def encode_texts(
    texts: List[str],
    stoi: Dict[str, int],
    max_len: int,
) -> np.ndarray:
    from .preprocess import tokenize_simple

    unk = stoi.get("<unk>", 1)
    pad = stoi.get("<pad>", 0)
    arr = np.full((len(texts), max_len), pad, dtype=np.int64)
    for i, text in enumerate(texts):
        toks = tokenize_simple(text)[:max_len]
        for j, tok in enumerate(toks):
            arr[i, j] = stoi.get(tok, unk)
    return arr


def save_lstm_bundle(
    path: Path,
    model: CommentLSTM,
    stoi: Dict[str, int],
    max_len: int,
    label_names: Tuple[str, ...] = ("neg", "neu", "pos"),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_state": model.state_dict(),
            "stoi": stoi,
            "max_len": max_len,
            "label_names": list(label_names),
            "hparams": {
                "vocab_size": model.embedding.num_embeddings,
                "embed_dim": model.embedding.embedding_dim,
                "hidden_dim": model.lstm.hidden_size,
                "num_classes": model.fc.out_features,
                "padding_idx": model.padding_idx,
            },
        },
        path,
    )


def load_lstm_bundle(path: Path, map_location: str | None = None) -> Tuple[CommentLSTM, Dict[str, int], int]:
    try:
        blob = torch.load(path, map_location=map_location, weights_only=False)
    except TypeError:
        blob = torch.load(path, map_location=map_location)
    hp = blob["hparams"]
    model = CommentLSTM(
        vocab_size=hp["vocab_size"],
        embed_dim=hp["embed_dim"],
        hidden_dim=hp["hidden_dim"],
        num_classes=hp["num_classes"],
        padding_idx=hp.get("padding_idx", 0),
    )
    model.load_state_dict(blob["model_state"])
    model.eval()
    return model, blob["stoi"], int(blob["max_len"])
