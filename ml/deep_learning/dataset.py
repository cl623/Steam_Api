"""PyTorch Dataset and DataLoader factory for the LSTM price-prediction model.

Converts the existing 2D price-history rows in SQLite into 3D sliding-window
tensors of shape ``(sequence_length, num_temporal_features)`` along with a
separate static-feature vector per sample.

Tensor layout
-------------
Each sample returned by ``__getitem__`` is a dict with:
    sequence  : FloatTensor  (seq_len, F_temporal)
    static    : FloatTensor  (F_static,)
    target    : FloatTensor  scalar – log-return over the prediction horizon
    item_name : str
    timestamp : str  – ISO timestamp of the prediction point
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset, DataLoader

from ..feature_extractor import ItemFeatureExtractor

logger = logging.getLogger(__name__)

# ── constants ───────────────────────────────────────────────────────────────
MAX_ABS_RETURN = 3.0
MIN_VOLUME_MA7 = 2.0

# Temporal (per-timestep) feature columns produced by _build_temporal_features
TEMPORAL_FEATURE_COLS: List[str] = [
    "price",
    "volume",
    "price_ma7",
    "price_ma30",
    "price_std7",
    "volume_ma7",
    "ret_7",
    "ret_30",
    "day_of_week",
    "month",
    "num_events",
    "has_event_today",
    "is_major_today",
    "max_stars_prev_7d",
    "max_stars_prev_30d",
    "days_until_next_event",
    "days_until_next_major",
    "days_until_next_sale",
    "price_band",
    "volume_band",
]

# Static (per-item) feature keys in order, from ItemFeatureExtractor
STATIC_FEATURE_KEYS: List[str] = [
    "type_weapon_skin",
    "type_sticker",
    "type_case",
    "type_agent",
    "type_gloves",
    "type_knife",
    "type_other",
    "is_weapon_skin",
    "condition_quality",
    "is_stattrak",
    "is_souvenir",
    "has_sticker",
    "is_case",
    "is_sticker",
    "is_agent",
    "is_gloves",
    "is_knife",
]

NUM_TEMPORAL_FEATURES = len(TEMPORAL_FEATURE_COLS)
NUM_STATIC_FEATURES = len(STATIC_FEATURE_KEYS)


@dataclass
class ItemSequenceBundle:
    """All sliding-window samples for one market item."""

    market_hash_name: str
    sequences: List[np.ndarray] = field(default_factory=list)
    statics: List[np.ndarray] = field(default_factory=list)
    targets: List[float] = field(default_factory=list)
    timestamps: List[str] = field(default_factory=list)


def flatten_item_bundles(
    bundles: List[ItemSequenceBundle],
) -> Tuple[List[np.ndarray], List[np.ndarray], List[float], List[str], List[str]]:
    """Concatenate per-item bundles into the flat lists used by ``SteamMarketSequenceDataset``."""
    all_seqs: List[np.ndarray] = []
    all_statics: List[np.ndarray] = []
    all_targets: List[float] = []
    all_names: List[str] = []
    all_ts: List[str] = []
    for b in bundles:
        all_seqs.extend(b.sequences)
        all_statics.extend(b.statics)
        all_targets.extend(b.targets)
        all_names.extend([b.market_hash_name] * len(b.targets))
        all_ts.extend(b.timestamps)
    return all_seqs, all_statics, all_targets, all_names, all_ts


# ── helpers ─────────────────────────────────────────────────────────────────

def _parse_steam_timestamp(ts_str: str) -> pd.Timestamp:
    """Parse the Steam text timestamp format into a pandas Timestamp."""
    import re
    try:
        clean_ts = re.sub(r"\s+\+\d+$", "", str(ts_str)).strip()
        parts = re.match(r"(\w+)\s+(\d+)\s+(\d+)\s+(\d+):", clean_ts)
        if parts:
            month_names = [
                "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
            ]
            month = month_names.index(parts.group(1)) + 1
            day = int(parts.group(2))
            year = int(parts.group(3))
            hour = int(parts.group(4))
            return pd.Timestamp(year, month, day, hour)
    except (ValueError, AttributeError, IndexError):
        pass
    return pd.NaT


def _get_price_band(price: float, item_type: str) -> float:
    """Mirror PricePredictor._get_price_band for consistency."""
    if price is None or price <= 0:
        return 0.0
    bands = {
        "weapon_skin": [(0.10, 0.0), (1.0, 1.0), (10.0, 2.0)],
        "sticker":     [(0.25, 0.0), (2.0, 1.0), (15.0, 2.0)],
        "gloves":      [(50.0, 1.0), (150.0, 2.0)],
        "knife":       [(100.0, 1.0), (300.0, 2.0)],
    }
    for threshold, band in bands.get(item_type, [(0.25, 0.0), (2.0, 1.0), (20.0, 2.0)]):
        if price < threshold:
            return band
    return 3.0


def _get_volume_band(volume: float) -> float:
    if volume is None or volume <= 0:
        return 0.0
    if volume < 5:
        return 0.0
    if volume < 50:
        return 1.0
    if volume < 500:
        return 2.0
    return 3.0


def _item_type_label(feature_vec: Dict[str, float]) -> str:
    for key, label in [
        ("type_weapon_skin", "weapon_skin"),
        ("type_sticker", "sticker"),
        ("type_gloves", "gloves"),
        ("type_knife", "knife"),
    ]:
        if feature_vec.get(key) == 1.0:
            return label
    return "other"


# ── data loading ────────────────────────────────────────────────────────────

def load_item_bundles_from_db(
    db_path: str | Path,
    game_id: str = "730",
    seq_len: int = 30,
    prediction_days: int = 7,
    max_items: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    use_event_window: bool = False,
    pre_event_days: int = 14,
    post_event_days: int = 30,
) -> List[ItemSequenceBundle]:
    """Load one ``ItemSequenceBundle`` per eligible item (for item-level splits)."""
    db_path = str(db_path)
    feature_extractor = ItemFeatureExtractor()
    bundles: List[ItemSequenceBundle] = []

    with sqlite3.connect(db_path) as conn:
        if use_event_window and from_date is None:
            try:
                ev = pd.read_sql_query(
                    "SELECT MIN(start_date) AS s, MAX(end_date) AS e FROM cs2_events",
                    conn, parse_dates=["s", "e"],
                )
                if not ev.empty and pd.notna(ev["s"].iloc[0]):
                    from_date = (ev["s"].iloc[0].normalize() - pd.Timedelta(days=pre_event_days)).date().isoformat()
                    to_date = (ev["e"].iloc[0].normalize() + pd.Timedelta(days=post_event_days)).date().isoformat()
                    logger.info("Event window: %s to %s", from_date, to_date)
            except Exception as exc:
                logger.warning("Could not derive event window: %s", exc)

        from_ts = pd.to_datetime(from_date).normalize() if from_date else None
        to_ts = pd.to_datetime(to_date).normalize() if to_date else None

        event_df = _load_event_daily(conn)

        min_entries = seq_len + prediction_days
        items_df = pd.read_sql_query(
            """
            SELECT i.id, i.market_hash_name, COUNT(ph.id) AS cnt
            FROM items i
            JOIN price_history ph ON i.id = ph.item_id
            WHERE i.game_id = ?
            GROUP BY i.id, i.market_hash_name
            HAVING cnt >= ?
            ORDER BY cnt DESC
            """,
            conn,
            params=(game_id, min_entries),
        )
        if max_items is not None:
            items_df = items_df.head(max_items)
        logger.info("Processing %d items for deep-learning dataset", len(items_df))

        total_samples = 0
        for idx, item in items_df.iterrows():
            seqs, statics, targets, _names, ts = _process_item(
                conn, item, feature_extractor, event_df,
                seq_len, prediction_days, from_ts, to_ts,
            )
            if targets:
                bundles.append(
                    ItemSequenceBundle(
                        market_hash_name=item["market_hash_name"],
                        sequences=seqs,
                        statics=statics,
                        targets=targets,
                        timestamps=ts,
                    )
                )
                total_samples += len(targets)

            if (idx + 1) % 25 == 0:
                logger.info("  items processed: %d/%d  samples so far: %d",
                            idx + 1, len(items_df), total_samples)

    logger.info(
        "Total items with samples: %d  total samples: %d  seq_len=%d  temporal_features=%d",
        len(bundles), total_samples, seq_len, NUM_TEMPORAL_FEATURES,
    )
    return bundles


def load_sequences_from_db(
    db_path: str | Path,
    game_id: str = "730",
    seq_len: int = 30,
    prediction_days: int = 7,
    max_items: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    use_event_window: bool = False,
    pre_event_days: int = 14,
    post_event_days: int = 30,
) -> Tuple[List[np.ndarray], List[np.ndarray], List[float], List[str], List[str]]:
    """Read SQLite and return flat sliding-window lists (pooled item order)."""
    bundles = load_item_bundles_from_db(
        db_path, game_id, seq_len, prediction_days,
        max_items, from_date, to_date, use_event_window,
        pre_event_days, post_event_days,
    )
    flat = flatten_item_bundles(bundles)
    logger.info(
        "Total samples: %d  static_features=%d",
        len(flat[2]), NUM_STATIC_FEATURES,
    )
    return flat


def _load_event_daily(conn: sqlite3.Connection) -> Optional[pd.DataFrame]:
    """Load the cs2_event_daily table including forward-looking countdowns."""
    try:
        df = pd.read_sql_query(
            """
            SELECT date, num_events, has_event_today, is_major_today,
                   max_stars_prev_7d, max_stars_prev_30d,
                   days_until_next_event, days_until_next_major,
                   days_until_next_sale
            FROM cs2_event_daily
            """,
            conn,
            parse_dates=["date"],
        )
        return df if not df.empty else None
    except Exception as exc:
        logger.warning("cs2_event_daily not available: %s", exc)
        return None


def _process_item(
    conn: sqlite3.Connection,
    item: pd.Series,
    feature_extractor: ItemFeatureExtractor,
    event_df: Optional[pd.DataFrame],
    seq_len: int,
    prediction_days: int,
    from_ts: Optional[pd.Timestamp],
    to_ts: Optional[pd.Timestamp],
) -> Tuple[List[np.ndarray], List[np.ndarray], List[float], List[str], List[str]]:
    """Build sliding-window sequences for a single item."""
    seqs, statics, targets, names, timestamps = [], [], [], [], []

    price_df = pd.read_sql_query(
        "SELECT timestamp, price, volume FROM price_history WHERE item_id = ? ORDER BY timestamp ASC",
        conn, params=(item["id"],),
    )
    if len(price_df) < seq_len + prediction_days:
        return seqs, statics, targets, names, timestamps

    price_df["timestamp"] = price_df["timestamp"].apply(_parse_steam_timestamp)
    price_df = price_df.dropna(subset=["timestamp"])
    if from_ts is not None:
        price_df = price_df[price_df["timestamp"] >= from_ts]
    if to_ts is not None:
        price_df = price_df[price_df["timestamp"] <= to_ts]
    if len(price_df) < seq_len + prediction_days:
        return seqs, statics, targets, names, timestamps

    price_df = _build_temporal_features(price_df, event_df, item, feature_extractor)
    if price_df is None or len(price_df) < seq_len + prediction_days:
        return seqs, statics, targets, names, timestamps

    # Static features (same for every window of this item)
    item_feat = feature_extractor.get_feature_vector(item["market_hash_name"])
    static_vec = np.array([item_feat[k] for k in STATIC_FEATURE_KEYS], dtype=np.float32)

    temporal_matrix = price_df[TEMPORAL_FEATURE_COLS].values.astype(np.float32)
    prices = price_df["price"].values
    ts_series = price_df["timestamp"]

    # Sliding windows: each window of seq_len rows, target is the return
    # from the last row of the window to `prediction_days` steps ahead.
    max_start = len(price_df) - seq_len - prediction_days
    for i in range(max_start + 1):
        window = temporal_matrix[i : i + seq_len]
        current_price = prices[i + seq_len - 1]
        future_price = prices[i + seq_len - 1 + prediction_days]

        if current_price is None or current_price <= 0:
            continue

        raw_return = (future_price - current_price) / current_price
        clipped = float(np.clip(raw_return, -MAX_ABS_RETURN, MAX_ABS_RETURN))
        log_ret = float(np.sign(clipped) * np.log1p(abs(clipped)))

        seqs.append(window)
        statics.append(static_vec)
        targets.append(log_ret)
        names.append(item["market_hash_name"])
        timestamps.append(ts_series.iloc[i + seq_len - 1].isoformat())

    return seqs, statics, targets, names, timestamps


def _build_temporal_features(
    price_df: pd.DataFrame,
    event_df: Optional[pd.DataFrame],
    item: pd.Series,
    feature_extractor: ItemFeatureExtractor,
) -> Optional[pd.DataFrame]:
    """Compute all per-timestep feature columns on *price_df* in-place."""
    if len(price_df) < 2:
        return None

    n = len(price_df)
    w7 = min(7, n - 1) if n > 1 else 1
    w30 = min(30, n - 1) if n > 1 else 1

    price_df = price_df.copy()
    price_df["price_ma7"] = price_df["price"].rolling(w7).mean().fillna(price_df["price"])
    price_df["price_ma30"] = price_df["price"].rolling(w30).mean().fillna(price_df["price"])
    price_df["price_std7"] = price_df["price"].rolling(w7).std().fillna(0.0)
    price_df["volume_ma7"] = price_df["volume"].rolling(w7).mean().fillna(price_df["volume"])
    price_df["ret_7"] = price_df["price"].pct_change(periods=min(7, n - 1)).fillna(0.0)
    price_df["ret_30"] = price_df["price"].pct_change(periods=min(30, n - 1)).fillna(0.0)

    price_df["day_of_week"] = price_df["timestamp"].dt.dayofweek.astype(float)
    price_df["month"] = price_df["timestamp"].dt.month.astype(float)

    # Event features
    event_cols = [
        "num_events", "has_event_today", "is_major_today",
        "max_stars_prev_7d", "max_stars_prev_30d",
        "days_until_next_event", "days_until_next_major", "days_until_next_sale",
    ]
    if event_df is not None and not event_df.empty:
        price_df["date"] = price_df["timestamp"].dt.normalize()
        price_df = price_df.merge(event_df, how="left", on="date")
        for col in event_cols:
            if col in price_df.columns:
                price_df[col] = price_df[col].fillna(0.0)
            else:
                price_df[col] = 0.0
    else:
        for col in event_cols:
            price_df[col] = 0.0

    # Bands
    item_feat = feature_extractor.get_feature_vector(item["market_hash_name"])
    it_label = _item_type_label(item_feat)
    price_df["price_band"] = price_df["price"].apply(lambda p: _get_price_band(p, it_label))
    price_df["volume_band"] = price_df["volume_ma7"].apply(_get_volume_band)

    # Filter very illiquid rows
    price_df = price_df[price_df["volume_ma7"] >= MIN_VOLUME_MA7]

    if len(price_df) == 0:
        return None

    price_df = price_df.reset_index(drop=True)
    return price_df


# ── PyTorch Dataset ─────────────────────────────────────────────────────────

class SteamMarketSequenceDataset(Dataset):
    """A map-style PyTorch Dataset that yields pre-built sliding-window samples.

    Each sample is a dict::

        {
            "sequence": FloatTensor (seq_len, F_temporal),
            "static":   FloatTensor (F_static,),
            "target":   FloatTensor scalar,
            "item_name": str,
            "timestamp": str,
        }
    """

    def __init__(
        self,
        sequences: List[np.ndarray],
        statics: List[np.ndarray],
        targets: List[float],
        item_names: List[str],
        timestamps: List[str],
    ):
        assert len(sequences) == len(targets), "sequence/target length mismatch"
        self.sequences = sequences
        self.statics = statics
        self.targets = targets
        self.item_names = item_names
        self.timestamps = timestamps

    def __len__(self) -> int:
        return len(self.targets)

    def __getitem__(self, idx: int) -> Dict:
        return {
            "sequence": torch.from_numpy(self.sequences[idx]),
            "static": torch.from_numpy(self.statics[idx]),
            "target": torch.tensor(self.targets[idx], dtype=torch.float32),
            "item_name": self.item_names[idx],
            "timestamp": self.timestamps[idx],
        }


def _collate_fn(batch: List[Dict]) -> Dict:
    """Custom collate that stacks tensors and keeps metadata as lists."""
    return {
        "sequence": torch.stack([b["sequence"] for b in batch]),
        "static": torch.stack([b["static"] for b in batch]),
        "target": torch.stack([b["target"] for b in batch]),
        "item_name": [b["item_name"] for b in batch],
        "timestamp": [b["timestamp"] for b in batch],
    }


# ── DataLoader factory ──────────────────────────────────────────────────────

def _make_loaders_from_flat(
    train_seqs: List[np.ndarray],
    train_stat: List[np.ndarray],
    train_tgt: List[float],
    train_names: List[str],
    train_ts: List[str],
    test_seqs: List[np.ndarray],
    test_stat: List[np.ndarray],
    test_tgt: List[float],
    test_names: List[str],
    test_ts: List[str],
    batch_size: int,
    num_workers: int,
    normalizer,
) -> Tuple[DataLoader, DataLoader, Any]:
    if not train_tgt:
        raise ValueError("Train split is empty – adjust split parameters or max_items")
    if not test_tgt:
        raise ValueError("Test split is empty – adjust split parameters or max_items")

    from .normalization import SequenceNormalizer

    if normalizer is None:
        normalizer = SequenceNormalizer()
        normalizer.fit(train_seqs)

    train_seqs = normalizer.transform(train_seqs)
    test_seqs = normalizer.transform(test_seqs)

    train_ds = SteamMarketSequenceDataset(
        train_seqs, train_stat, train_tgt, train_names, train_ts,
    )
    test_ds = SteamMarketSequenceDataset(
        test_seqs, test_stat, test_tgt, test_names, test_ts,
    )

    train_loader = DataLoader(
        train_ds, batch_size=batch_size, shuffle=False,
        collate_fn=_collate_fn, num_workers=num_workers,
    )
    test_loader = DataLoader(
        test_ds, batch_size=batch_size, shuffle=False,
        collate_fn=_collate_fn, num_workers=num_workers,
    )
    return train_loader, test_loader, normalizer


def build_dataloaders(
    db_path: str | Path,
    game_id: str = "730",
    seq_len: int = 30,
    prediction_days: int = 7,
    batch_size: int = 64,
    train_ratio: float = 0.8,
    max_items: Optional[int] = None,
    use_event_window: bool = False,
    num_workers: int = 0,
    normalizer=None,
    split_mode: Literal["pooled", "item_holdout"] = "pooled",
    holdout_fraction: float = 0.2,
    holdout_seed: int = 42,
) -> Tuple[DataLoader, DataLoader, Optional[object], Dict[str, Any]]:
    """Load SQLite windows, split, normalize, and build DataLoaders.

    Parameters
    ----------
    split_mode
        * ``pooled`` – single chronological split on the flat sample list (legacy;
          windows from the same item can appear in both train and test).
        * ``item_holdout`` – assign whole items to train or test; tests
          generalization to **unseen** ``market_hash_name`` values.
    holdout_fraction
        Fraction of items reserved for test when ``split_mode=item_holdout``.
    holdout_seed
        RNG seed for choosing which items are held out.

    Returns
    -------
    train_loader, test_loader, normalizer, meta
        ``meta`` includes ``split_mode``, item lists (for holdout), and sample counts.
    """
    bundles = load_item_bundles_from_db(
        db_path, game_id, seq_len, prediction_days,
        max_items=max_items, use_event_window=use_event_window,
    )
    if not bundles:
        raise ValueError("No samples produced – check your database and parameters")

    meta: Dict[str, Any] = {"split_mode": split_mode}

    if split_mode == "pooled":
        seqs, statics, targets, names, ts = flatten_item_bundles(bundles)
        n = len(targets)
        split = int(n * train_ratio)
        train_seqs, test_seqs = seqs[:split], seqs[split:]
        train_stat, test_stat = statics[:split], statics[split:]
        train_tgt, test_tgt = targets[:split], targets[split:]
        train_names, test_names = names[:split], names[split:]
        train_ts, test_ts = ts[:split], ts[split:]
        meta.update(
            {
                "train_samples": len(train_tgt),
                "test_samples": len(test_tgt),
                "train_items": sorted({n for n in train_names}),
                "test_items": sorted({n for n in test_names}),
            }
        )
    elif split_mode == "item_holdout":
        n_items = len(bundles)
        if n_items < 2:
            raise ValueError("item_holdout requires at least 2 items with samples")
        rng = np.random.RandomState(holdout_seed)
        perm = rng.permutation(n_items)
        n_hold = max(1, int(round(n_items * holdout_fraction)))
        train_bundles = [bundles[int(i)] for i in perm[n_hold:]]
        test_bundles = [bundles[int(i)] for i in perm[:n_hold]]
        if not train_bundles or not test_bundles:
            raise ValueError("Item holdout produced an empty train or test set")
        train_seqs, train_stat, train_tgt, train_names, train_ts = flatten_item_bundles(train_bundles)
        test_seqs, test_stat, test_tgt, test_names, test_ts = flatten_item_bundles(test_bundles)
        train_item_names = sorted({b.market_hash_name for b in train_bundles})
        test_item_names = sorted({b.market_hash_name for b in test_bundles})
        meta.update(
            {
                "train_samples": len(train_tgt),
                "test_samples": len(test_tgt),
                "train_items": train_item_names,
                "test_items": test_item_names,
                "holdout_fraction": holdout_fraction,
                "holdout_seed": holdout_seed,
            }
        )
        logger.info(
            "Item holdout: %d train items, %d test items | train samples=%d test samples=%d",
            len(train_item_names), len(test_item_names), len(train_tgt), len(test_tgt),
        )
        logger.info("Held-out items: %s", test_item_names)
    else:
        raise ValueError(f"Unknown split_mode: {split_mode}")

    train_loader, test_loader, normalizer = _make_loaders_from_flat(
        train_seqs, train_stat, train_tgt, train_names, train_ts,
        test_seqs, test_stat, test_tgt, test_names, test_ts,
        batch_size, num_workers, normalizer,
    )

    logger.info("DataLoaders ready: train=%d  test=%d  batch=%d",
                len(train_loader.dataset), len(test_loader.dataset), batch_size)
    return train_loader, test_loader, normalizer, meta
