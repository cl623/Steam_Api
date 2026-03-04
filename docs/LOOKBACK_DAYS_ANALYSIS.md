# Does Increasing lookback_days Improve Model Accuracy?

## Short Answer

**Not directly.** In the current code, `lookback_days` only sets the **minimum amount of history** required per item. It does **not** change how much history is used to compute features. So raising it (e.g. 7 → 30) mainly **reduces** how many items/samples you train on; it can slightly improve or slightly hurt accuracy depending on the data, but it does **not** add “more lookback” to the model’s inputs.

To actually use more history for accuracy, you’d add **longer-window features** (e.g. 60- or 90-day moving averages) or change how features are built, not only increase `lookback_days`.

---

## What lookback_days Actually Does

In `prepare_data()`:

1. **Minimum data requirement**
   - `min_entries = lookback_days + prediction_days`
   - Example: `lookback_days=7`, `prediction_days=7` → need at least **14** rows per item.
   - Example: `lookback_days=30`, `prediction_days=7` → need at least **37** rows per item.

2. **Item filtering**
   - Items with fewer than `lookback_days + prediction_days` rows are **skipped**.
   - So increasing `lookback_days` **excludes** more items (those with shorter history).

3. **Feature computation**
   - Rolling features use the **full** `price_df` for each item.
   - Windows are: **7** (price_ma7, price_std7, volume_ma7) and **30** (price_ma30).
   - Those window lengths are **fixed**; they do **not** depend on `lookback_days`.

So:

- **Increasing `lookback_days`** = stricter filter (only items with more history).
- **It does not** add longer windows or new features; the “lookback” in the model is still 7 and 30 days.

---

## Effect of Increasing lookback_days (e.g. 7 → 30)

| Aspect | lookback_days = 7 | lookback_days = 30 |
|--------|-------------------|---------------------|
| Min entries per item | 14 | 37 |
| Items that qualify | More | Fewer |
| Total training samples | More | Fewer |
| Feature windows | Still 7 and 30 days | Still 7 and 30 days |
| “Amount of lookback” in features | Unchanged | Unchanged |

Possible outcomes:

- **Slightly better accuracy** if items with very short history are noisier and dropping them improves signal.
- **Slightly worse accuracy** if you lose too much training data (fewer items/samples).
- **No big change** if most items already have long history.

So: increasing `lookback_days` alone is **not** a reliable way to improve accuracy; it’s a data filter, not a feature change.

---

## How to Actually Use More History for Accuracy

To make the model use **longer** history, you need to change **features**, not only the minimum-data filter:

1. **Add longer-window features** (recommended)
   - e.g. 60-day or 90-day moving average, or volatility over 30 days.
   - These give the model explicit “longer lookback” signals.

2. **Keep lookback_days as a filter**
   - If you add e.g. a 60-day MA, you’d want at least 60 + prediction_days rows.
   - So you might set `lookback_days` to match the longest window (e.g. 60 or 90) so that only items with enough history are used. That way you’re not just “increasing lookback_days” for its own sake, but aligning the **minimum data** with the **longest feature window**.

---

## Recommendation

- **Don’t** expect a clear accuracy gain from **only** increasing `lookback_days` (e.g. 7 → 30). It mainly reduces dataset size and can go either way.
- **Do** consider:
  - Adding **longer-window features** (e.g. 60- or 90-day MA) if you want the model to use more history.
  - Optionally setting `lookback_days` to the longest window you use, so every item has enough data for that feature.

So: **increasing the lookback_days parameter by itself is unlikely to improve accuracy in a meaningful way**; improving accuracy from “more lookback” comes from **longer-window features** (and then possibly a matching `lookback_days` for filtering).
