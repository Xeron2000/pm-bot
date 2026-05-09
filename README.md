# pm-bot

Automated trading system for [Polymarket](https://polymarket.com) daily weather markets. Fetches multi-source forecasts, generates strategy signals, and executes maker-only limit orders via the CLOB API.

## Strategy

The sole active strategy is **gopfan2** (tail-YES lottery):

| Strategy | Signal | Edge Source |
|---|---|---|
| `gopfan2` | Buy cheap YES on tail buckets (≤$0.15) where model probability > market price + 2pp | Model-vs-market divergence on extreme temperature outcomes |

**Why only gopfan2?** Five strategies were removed on 2026-05-07 after live trading analysis:
- `neg_risk_field_fade`, `neg_risk_sum`: core is tail-NO, live fill rate <1%
- `truncation_edge`, `resolution_div`: mid-bucket trades are all negative EV
- `ensemble_spread`: total P&L was negative

## Quick Start

```bash
# Install
uv sync

# Configure
cp config.toml.example config.toml
# Edit config.toml — add CLOB API credentials
# Set POLY_PK env var for wallet private key

# Scan live markets (read-only)
pm-bot scan --cities "New York,London,Tokyo"

# Scan with intraday observation filtering (after 5PM local)
pm-bot scan --cities "New York" --observed

# Explain a specific market
pm-bot explain <condition-id>

# Backtest (90 days, real CLOB prices)
pm-bot backtest --strategy gopfan2 --days 90 --bankroll 100 --live

# Portfolio backtest with custom sizing
pm-bot backtest --days 90 --bankroll 100 --live --kelly 0.10 --stop-loss 0.2

# Live trade (requires credentials)
pm-bot trade --confirm

# Daemon mode (automated scanning + trading + settle)
pm-bot daemon start --dry-run --cities "NYC,London,Tokyo"

# Paper trading P&L
pm-bot paper-pnl

# Claim winnings
pm-bot settle --all
```

## Architecture

```
pm_bot/
├── models/          # Data models (WeatherEvent, TemperatureBucket, ForecastResult)
├── core/
│   ├── parser.py    # Market question → TemperatureBucket parsing (14 regex patterns)
│   ├── weather.py   # Open-Meteo forecast + 31-member GEFS ensemble
│   ├── aggregation.py  # BMA consensus (GFS + ECMWF + NWS + METAR)
│   ├── observation.py  # AWC METAR real-time observation + anomaly detection
│   ├── clob.py      # CLOB API trading (auth, orders, heartbeat, settle)
│   ├── kelly.py     # Position sizing (fractional Kelly, default 10%)
│   ├── risk.py      # 3-level circuit breaker + risk limits
│   ├── station_bias.py  # EMA-based per-station forecast bias correction
│   └── db.py        # SQLite trade persistence
├── strategies/
│   └── base.py      # Gopfan2Strategy (tail-YES lottery)
├── backtest/
│   ├── engine.py    # BacktestEngine (synthetic + real CLOB + portfolio)
│   ├── costs.py     # CostModel + FillModel (maker/taker fees, fill probabilities)
│   ├── metrics.py   # Sharpe, Sortino, MaxDD, Brier score
│   └── real_data.py # Gamma API + CLOB price history + Open-Meteo archive
└── cli/             # Typer commands (scan, trade, watch, daemon, settle, backtest, paper-pnl)
```

## Key Design Decisions

- **Maker-only**: All live trades use limit orders (zero taker fee). Fill model applies ~50% fill probability for mid-buckets, ~10% for tail prices ($0.01-$0.15).
- **Floor truncation**: Polymarket settles on `floor(observed_temp)`. Bucket boundaries use exclusive upper bound for °C, inclusive for °F (2°F wide).
- **ERA5 bias correction**: Open-Meteo archive (ERA5 reanalysis) systematically underestimates Tmax by -0.5 to -1.2°C vs Weather Underground ASOS. Per-city correction applied in backtests; EMA-based station bias correction with 30-day warmup and ERA5 priors for live trading.
- **31-member GEFS ensemble**: Uses all 31 GFS ensemble members (upgraded from 21) for probability estimation. Falls back to Gaussian CDF with σ=2.5°C when ensemble unavailable.
- **BMA consensus**: Bayesian Model Averaging across Open-Meteo, NWS, and METAR sources. Agreement score penalizes edge when sources disagree.
- **Fractional Kelly (10%)**: Position sizing uses Kelly criterion at 10% fraction. More conservative than the previous 25% to account for probability estimation uncertainty.
- **V2 auto-settle**: Daemon calls `poly_web3.redeem_all()` via Relayer each trade cycle; redeemed pUSD added back to bankroll.

## Backtest Results (90-day, live-mode, $100 bankroll)

Live-mode constraints: maker-only, $50/position cap, 8%+ edge threshold, fill model, forecast penalty.

| Config | Return | Sharpe | Trades | Win% |
|---|---|---|---|---|
| Portfolio TOP-3 (k=0.10, sl=20%) | +699% | 5.1 | 101 | 36% |
| Best single (k=0.10, sl=20%) | +422% | 4.8 | 46 | 39% |

**Caveats**: These results are from synthetic backtests with model-derived prices. Real-money results will differ due to:
- Spread and slippage on thin orderbooks
- Model probability estimation error (ensemble under-dispersion)
- Station bias not fully calibrated in backtests
- 90-day sample size insufficient for statistical confidence

## Data Sources

| Source | Purpose | Auth |
|---|---|---|
| Polymarket CLOB API | Order book, trade execution | L1 wallet + L2 HMAC |
| Polymarket Gamma API | Market metadata, resolved events | None |
| Open-Meteo forecast API | GFS deterministic forecast | None |
| Open-Meteo ensemble API | 31-member GEFS ensemble | None |
| Open-Meteo archive API | ERA5 reanalysis (observed temps) | None |
| AWC METAR API | Real-time airport observations | None |
| NWS API | US city forecasts | None |
| Weather Underground | Settlement station (parsed from market rules) | None |

## Risks

- Tail bucket liquidity is thin ($10-50 depth at $0.03-0.15 prices)
- Polymarket silently changes settlement stations without announcement
- 10-second heartbeat timeout kills all open orders since Jan 2026
- 425 matching engine restart every Tue 7AM ET (~90s)
- Only 3 cities (NYC, London, Tokyo) have reliably active daily markets
- Backtest uses ~42% forecast-derived fallback prices for inactive markets
- No out-of-sample validation — backtest results may not generalize
- Ensemble under-dispersion (GFS spread typically 60-80% of true uncertainty)

## Development

```bash
# Lint
ruff check pm_bot/

# Type check
mypy pm_bot/

# Test (958 tests)
pytest tests/ -q

# Run with debug logging
pm-bot scan --cities "New York" --verbose
```

## License

MIT License. See [LICENSE](LICENSE) for details.

## Disclaimer

This software is for educational and research purposes only. Trading on prediction markets involves significant financial risk. Past backtest performance does not guarantee future results. The authors are not responsible for any financial losses incurred through use of this software.
