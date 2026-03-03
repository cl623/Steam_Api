import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd


def build_event_timeline(matches: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate raw HLTV CS2 match data into an event-level table.

    Expected columns in `matches`:
      - event_name
      - time (datetime64)
      - stars_of_tournament
    """
    events = (
        matches.groupby("event_name")
        .agg(
            start_date=("time", "min"),
            end_date=("time", "max"),
            num_matches=("time", "size"),
            stars=("stars_of_tournament", "max"),
        )
        .reset_index()
    )

    events["start_date"] = events["start_date"].dt.normalize()
    events["end_date"] = events["end_date"].dt.normalize()
    events["duration_days"] = (events["end_date"] - events["start_date"]).dt.days + 1

    return events


def build_daily_event_features(events: pd.DataFrame) -> pd.DataFrame:
    """
    Build a daily CS2 event feature table suitable for joining with price history.

    For each calendar date between the earliest and latest event, we compute:
      - num_events: number of distinct events active that day
      - max_stars: max stars among events active that day
      - has_event_today: 1 if any event active, else 0
      - is_major_today: 1 if any event with stars >= 4 is active
      - max_stars_prev_7d: max stars over the previous 7 days (excluding today)
      - max_stars_prev_30d: max stars over the previous 30 days (excluding today)
    """
    if events.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "num_events",
                "max_stars",
                "has_event_today",
                "is_major_today",
                "max_stars_prev_7d",
                "max_stars_prev_30d",
            ]
        )

    # Expand each event into its active date range
    all_days = []
    for _, row in events.iterrows():
        dates = pd.date_range(row["start_date"], row["end_date"], freq="D")
        all_days.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "event_name": row["event_name"],
                    "stars": row["stars"],
                }
            )
        )

    if all_days:
        daily = pd.concat(all_days, ignore_index=True)
    else:
        daily = pd.DataFrame(columns=["date", "event_name", "stars"])

    # Aggregate to one row per date
    daily_agg = (
        daily.groupby("date")
        .agg(
            num_events=("event_name", "nunique"),
            max_stars=("stars", "max"),
        )
        .reset_index()
    )

    # Build a continuous daily index between min and max dates
    full_dates = pd.date_range(
        start=daily_agg["date"].min(), end=daily_agg["date"].max(), freq="D"
    )
    daily_full = (
        pd.DataFrame({"date": full_dates})
        .merge(daily_agg, on="date", how="left")
        .sort_values("date")
    )

    daily_full[["num_events", "max_stars"]] = daily_full[["num_events", "max_stars"]].fillna(
        0
    )

    # Basic flags
    daily_full["has_event_today"] = (daily_full["num_events"] > 0).astype(int)
    daily_full["is_major_today"] = (daily_full["max_stars"] >= 4).astype(int)

    # Past-window features (no lookahead): previous 7 and 30 days, excluding today
    shifted_max = daily_full["max_stars"].shift(1).fillna(0)
    daily_full["max_stars_prev_7d"] = (
        shifted_max.rolling(window=7, min_periods=1).max().fillna(0)
    )
    daily_full["max_stars_prev_30d"] = (
        shifted_max.rolling(window=30, min_periods=1).max().fillna(0)
    )

    return daily_full


def process_hltv_dataset(
    matches_csv_path: Path,
    db_path: Optional[Path] = None,
    events_table: str = "cs2_events",
    daily_table: str = "cs2_event_daily",
) -> None:
    """
    Load the HLTV CS2 matches dataset, build event-level and daily features,
    and optionally persist them into the main SQLite database.

    - matches_csv_path: path to the HLTV dataset CSV
    - db_path: if provided, tables will be written into this SQLite DB
    """
    matches = pd.read_csv(matches_csv_path)

    if "time" not in matches.columns:
        raise ValueError("Expected a 'time' column in the HLTV dataset.")

    # The raw HLTV column looks like "Results for October 24th 2024".
    # We normalize it to a proper date using an explicit format.
    raw_time = matches["time"].astype(str)
    cleaned = raw_time.str.replace(r"^Results for\s+", "", regex=True)
    cleaned = cleaned.str.replace(
        r"(\d{1,2})(st|nd|rd|th)", r"\1", regex=True
    )

    # First try the strict expected format, then fall back to dateutil if needed.
    parsed = pd.to_datetime(cleaned, format="%B %d %Y", errors="coerce")
    if parsed.isna().any():
        parsed_fallback = pd.to_datetime(cleaned, errors="coerce")
        parsed = parsed.fillna(parsed_fallback)

    matches["time"] = parsed

    # Drop rows where we could not parse a timestamp at all.
    matches = matches.dropna(subset=["time"])
    if matches.empty:
        raise ValueError("Failed to parse any timestamps from HLTV 'time' column.")

    required_cols = {"event_name", "time", "stars_of_tournament"}
    missing = required_cols - set(matches.columns)
    if missing:
        raise ValueError(f"Missing required columns in HLTV dataset: {missing}")

    events = build_event_timeline(matches)
    daily = build_daily_event_features(events)

    if db_path is not None:
        with sqlite3.connect(db_path) as conn:
            events.to_sql(events_table, conn, if_exists="replace", index=False)
            daily.to_sql(daily_table, conn, if_exists="replace", index=False)


def main() -> None:
    """
    Convenience CLI:
      - expects the HLTV dataset at data/hltv_match_resultscs2.csv
      - writes tables into data/market_data.db if it exists
    """
    project_root = Path(__file__).resolve().parents[1]
    default_csv = project_root / "data" / "hltv_match_resultscs2.csv"
    default_db = project_root / "data" / "market_data.db"

    if not default_csv.exists():
        raise FileNotFoundError(
            f"Expected HLTV dataset CSV at {default_csv}. "
            "Download it from Kaggle and place it there."
        )

    db_path: Optional[Path] = default_db if default_db.exists() else None
    process_hltv_dataset(default_csv, db_path=db_path)


if __name__ == "__main__":
    main()

