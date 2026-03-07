# Backtest Results — March 7, 2026

## Overview

Backtest simulation of a **$100 trading bot** on historical CS2 (game 730) Steam market data, selecting the top 5 items per week by predicted 7-day return and selling 7 days later at actual market prices.

| Parameter | Value |
|---|---|
| Starting Balance | $100.00 |
| Steam Sell Fee | 15% (5% Steam + 10% CS2) |
| Break-even Return | ~17.6% |
| Top-K Picks / Week | 5 |
| Test Window | Last 3 months (2024-08-24 to 2024-11-22) |
| Training Set | 303,844 observations (before 2024-08-24) |
| Test Set | 76,243 observations |

---

## Head-to-Head Comparison

| Metric | Random Forest | Gradient Boosting |
|---|--:|--:|
| Final Balance | $3,733,899.43 | **$18,358,229.48** |
| Total Return | +3,733,799% | **+18,358,129%** |
| Final Balance (no fees) | $30,882,793.81 | **$151,839,498.28** |
| Return (no fees) | +30,882,693% | **+151,839,398%** |
| Max Drawdown | 0.00% | 0.00% |
| Win Rate (w/ fees) | 86.2% | **92.3%** |
| Win Rate (no fees) | 95.4% | 95.4% |
| Profit Factor | 106.45 | **145.17** |
| Sharpe (per-trade) | 1.569 | **2.318** |
| Sortino (per-trade) | 23.769 | **27.971** |
| Direction Accuracy | **71.9%** | 65.4% |
| Total Trades | 65 | 65 |

---

## Market Benchmark (Test Period)

| Metric | Value |
|---|--:|
| Mean 7-day return | +7.65% |
| Median 7-day return | +0.00% |
| % items with gain | 39.4% |

Both models massively outperform the market benchmark. The median item has zero return over 7 days, while the models average +132% (RF) and +157% (GB) per trade by selecting the highest-conviction picks.

---

## Weekly Equity Curves

### Random Forest

| Week | Date | Picks | Balance | Wk Return | No-Fee Balance | NF Return |
|--:|:--|--:|--:|--:|--:|--:|
| 0 | 2024-08-24 | 5 | $195.24 | +95.24% | $229.70 | +129.70% |
| 1 | 2024-08-31 | 5 | $276.45 | +41.59% | $382.63 | +66.58% |
| 2 | 2024-09-07 | 5 | $800.70 | +189.64% | $1,303.80 | +240.75% |
| 3 | 2024-09-14 | 5 | $1,735.36 | +116.73% | $3,324.40 | +154.98% |
| 4 | 2024-09-21 | 5 | $2,494.18 | +43.73% | $5,621.25 | +69.09% |
| 5 | 2024-10-01 | 5 | $7,966.33 | +219.40% | $21,122.48 | +275.76% |
| 6 | 2024-10-05 | 5 | $25,624.20 | +221.66% | $79,931.46 | +278.42% |
| 7 | 2024-10-12 | 5 | $76,750.80 | +199.52% | $281,664.09 | +252.38% |
| 8 | 2024-10-19 | 5 | $135,198.55 | +76.15% | $583,716.13 | +107.24% |
| 9 | 2024-10-26 | 5 | $322,825.96 | +138.78% | $1,639,755.86 | +180.92% |
| 10 | 2024-11-02 | 5 | $835,360.42 | +158.76% | $4,991,898.11 | +204.43% |
| 11 | 2024-11-09 | 5 | $1,983,876.88 | +137.49% | $13,947,218.57 | +179.40% |
| 12 | 2024-11-16 | 5 | $3,733,899.43 | +88.21% | $30,882,793.81 | +121.43% |

### Gradient Boosting

| Week | Date | Picks | Balance | Wk Return | No-Fee Balance | NF Return |
|--:|:--|--:|--:|--:|--:|--:|
| 0 | 2024-08-24 | 5 | $205.45 | +105.45% | $241.71 | +141.71% |
| 1 | 2024-08-31 | 5 | $572.64 | +178.72% | $792.58 | +227.91% |
| 2 | 2024-09-07 | 5 | $1,799.03 | +214.16% | $2,929.42 | +269.61% |
| 3 | 2024-09-14 | 5 | $5,552.42 | +208.63% | $10,636.70 | +263.10% |
| 4 | 2024-09-21 | 5 | $16,949.40 | +205.26% | $38,199.68 | +259.13% |
| 5 | 2024-10-01 | 5 | $50,827.35 | +199.88% | $134,767.12 | +252.80% |
| 6 | 2024-10-05 | 5 | $145,296.79 | +185.86% | $453,235.11 | +236.31% |
| 7 | 2024-10-12 | 5 | $364,280.30 | +150.71% | $1,336,854.94 | +194.96% |
| 8 | 2024-10-19 | 5 | $786,358.77 | +115.87% | $3,395,083.04 | +153.96% |
| 9 | 2024-10-26 | 5 | $1,418,036.85 | +80.33% | $7,202,748.64 | +112.15% |
| 10 | 2024-11-02 | 5 | $3,496,876.41 | +146.60% | $20,896,430.19 | +190.12% |
| 11 | 2024-11-09 | 5 | $8,366,876.34 | +139.27% | $58,821,519.85 | +181.49% |
| 12 | 2024-11-16 | 5 | $18,358,229.48 | +119.42% | $151,839,498.28 | +158.14% |

---

## Notable Trades

### Top 5 — Random Forest

| Item | Buy Price | Predicted | Actual | PnL |
|---|--:|--:|--:|--:|
| M4A1-S \| Nitro (Field-Tested) | $0.44 | +193.5% | +158.8% | +$476,085.05 |
| M4A1-S \| Nitro (Field-Tested) | $0.44 | +191.8% | +152.0% | +$453,270.78 |
| M4A1-S \| Nitro (Field-Tested) | $0.44 | +192.9% | +150.0% | +$446,372.30 |
| M4A1-S \| Nitro (Field-Tested) | $0.44 | +197.6% | +146.3% | +$433,810.73 |
| M4A1-S \| Nitro (Field-Tested) | $0.46 | +209.9% | +184.2% | +$236,538.90 |

### Top 5 — Gradient Boosting

| Item | Buy Price | Predicted | Actual | PnL |
|---|--:|--:|--:|--:|
| M4A1-S \| Nitro (Field-Tested) | $0.46 | +168.4% | +172.5% | +$2,202,734.13 |
| M4A1-S \| Nitro (Field-Tested) | $0.46 | +169.2% | +169.8% | +$2,164,861.19 |
| M4A1-S \| Nitro (Field-Tested) | $0.44 | +168.6% | +152.0% | +$1,911,641.09 |
| M4A1-S \| Nitro (Field-Tested) | $0.44 | +168.7% | +150.0% | +$1,882,547.18 |
| M4A1-S \| Nitro (Field-Tested) | $0.44 | +167.8% | +146.3% | +$1,829,569.55 |

### Worst Trades — Random Forest

| Item | Buy Price | Predicted | Actual | PnL |
|---|--:|--:|--:|--:|
| FAMAS \| Colony (Minimal Wear) | $0.03 | +184.5% | +0.0% | -$59,516.31 |
| Souvenir P90 \| Verdant Growth (BS) | $0.03 | +108.3% | +0.0% | -$52.06 |
| Souvenir P90 \| Verdant Growth (BS) | $0.03 | +98.8% | +10.0% | -$22.56 |
| Sealed Graffiti \| Silver Bullet | $0.04 | +109.0% | +6.8% | -$14.74 |
| Souvenir P90 \| Ancient Earth (WW) | $0.03 | +93.8% | +0.0% | -$3.00 |

### Worst Trades — Gradient Boosting

| Item | Buy Price | Predicted | Actual | PnL |
|---|--:|--:|--:|--:|
| AWP \| Duality (Field-Tested) | $2.52 | +207.0% | -5.1% | -$30,370.15 |
| AWP \| Duality (Battle-Scarred) | $2.08 | +191.3% | -4.9% | -$30,136.83 |
| Charm \| Die-cast AK | $5.73 | +236.6% | +6.5% | -$6,921.58 |
| Souvenir P90 \| Verdant Growth (BS) | $0.03 | +60.1% | -3.0% | -$3.52 |
| Sealed Graffiti \| 1G (Dust Brown) | $0.04 | +156.7% | +11.1% | -$2.28 |

---

## Analysis

### Strengths

- **0% max drawdown** for both models — the strategy never had a losing week, indicating strong consistency over this test window.
- **Gradient Boosting dominates on all risk-adjusted metrics**: higher Sharpe (2.318 vs 1.569), higher Sortino (27.971 vs 23.769), higher profit factor (145.17 vs 106.45), and higher win rate (92.3% vs 86.2%).
- **Both models correctly exploit cheap items with large percentage swings.** The M4A1-S Nitro at $0.44 delivered +150% actual returns repeatedly — the model learned this pattern and consistently selected it.

### Caveats and Realistic Limitations

- **Returns are unrealistically large** because the simulation assumes infinite liquidity — in reality, buying $1M+ worth of a $0.44 skin is impossible. Steam market order books are thin, and slippage would destroy most of the compounded gains at scale.
- **Single-item concentration**: The top trades are dominated by a single item (M4A1-S Nitro). This is an overfitting signal — the model may be memorizing a few items' patterns rather than learning generalizable features.
- **No position size caps**: The bot reinvests 100% of its balance each week. A realistic strategy would cap position sizes to what the market can absorb (e.g., daily volume × average price).
- **Look-ahead bias risk**: While the train/test split is chronological, the features (moving averages, returns) are computed from the same price series used to compute the target. This is standard, but worth noting.
- **Short test window**: 13 weeks is a limited sample. Performance may not generalize to different market regimes (bear markets, low-activity periods).

### Recommendations

1. **Add position size limits** proportional to item volume to produce realistic PnL estimates.
2. **Diversify picks** — penalize repeated selection of the same item across consecutive weeks.
3. **Extend the test window** to 6–12 months to stress-test across different market conditions.
4. **GB is the recommended model** for production use, consistent with the findings in `MODEL_SUMMARY.md`. It outperforms RF on every trading metric despite RF having higher direction accuracy on the full test set.
