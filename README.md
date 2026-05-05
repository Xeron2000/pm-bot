# pm-bot

Automated trading system for [Polymarket](https://polymarket.com) daily weather markets. Fetches multi-source forecasts, generates strategy signals, and executes maker-only limit orders via the CLOB API.

## Strategies

| Strategy | Signal Source | Best For |
|---|---|---|
| `neg_risk_field_fade` | ΣYES > $1.02 over-round | Structured pricing anomaly |
| `neg_risk_sum` | ΣYES < $0.98 arbitrage | Under-round opportunity |
| `truncation_edge` | Floor-truncation vs ±0.5 pricing | Bucket boundary bias |
| `gopfan2` | Barbell tail-buying (model-validated) | Tail price mispricing |
| `ensemble_spread` | High forecast σ → tail underpricing | Forecast disagreement |
| `resolution_div` | WU station vs NWS forecast divergence | Settlement source gap |

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

# Scan with intraday observation filtering
pm-bot scan --cities "New York" --observed

# Explain a specific market
pm-bot explain <condition-id>

# Backtest (90 days, real CLOB prices)
pm-bot backtest run --strategy truncation_edge --days 90 --bankroll 100 --live

# Portfolio backtest (all strategies, shared bankroll)
pm-bot backtest run --portfolio --days 90 --bankroll 100 --live --kelly 0.15 --stop-loss 0.2

# Live trade (requires credentials)
pm-bot trade --strategy neg_risk_field_fade --confirm

# Daemon mode (automated scanning + trading + settle)
pm-bot daemon

# Claim winnings
pm-bot settle --all
```

## Architecture

```
pm_bot/
├── models/          # Data models (WeatherEvent, TemperatureBucket, ForecastResult)
├── core/
│   ├── parser.py    # Market question → TemperatureBucket parsing
│   ├── weather.py   # Open-Meteo forecast fetching + bucket probability
│   ├── observation.py  # AWC METAR real-time observation + filtering
│   ├── clob.py      # CLOB API trading (auth, orders, heartbeat, settle)
│   ├── kelly.py     # Position sizing (Kelly criterion)
│   ├── risk.py      # Circuit breaker + risk limits
│   ├── aggregation.py  # Multi-source forecast consensus
│   └── db.py        # SQLite trade persistence
├── strategies/      # 6 signal generators (see table above)
├── backtest/
│   ├── engine.py    # BacktestEngine (synthetic + real CLOB + portfolio)
│   └── real_data.py # Gamma API + CLOB price history + Open-Meteo archive
└── cli/             # Typer commands (scan, trade, watch, daemon, settle, backtest)
```

## Key Design Decisions

- **Maker-only**: All live trades use limit orders (zero taker fee). Fill model applies 70% probability for normal buckets, <10% for tail prices.
- **Floor truncation**: Polymarket settles on `floor(observed_temp)`. Bucket boundaries use exclusive upper bound for °C, inclusive for °F (2°F wide).
- **ERA5 bias correction**: Open-Meteo archive (ERA5 reanalysis) systematically underestimates Tmax by -0.5 to -1.2°C vs Weather Underground ASOS. Per-city correction applied.
- **Seasonal ensemble calibration**: Synthetic ensemble σ scaled by city-month (summer 1.1-1.4×, winter 0.7-0.9×) × 1.15× GFS under-dispersion factor.
- **V2 auto-settle**: Daemon calls `poly_web3.redeem_all()` via Relayer each trade cycle; redeemed pUSD added back to bankroll.

## Backtest Results (90-day, live-mode, $100 bankroll)

Live-mode constraints: maker-only, $50/position cap, 8%+ edge threshold, fill model, forecast penalty, 8-city whitelist.

| Config | Return | Sharpe | Trades | Win% |
|---|---|---|---|---|
| Portfolio TOP-3 (k=0.15, sl=20%) | +699% | 5.1 | 101 | 36% |
| Best single (k=0.15, sl=20%) | +422% | 4.8 | 46 | 39% |

**Realistic expectation**: $100 → ~$500-700 over 3 months with compound reinvestment. MaxDD ≤4%.

## Data Sources

| Source | Purpose | Auth |
|---|---|---|
| Polymarket CLOB API | Order book, trade execution | L1 wallet + L2 HMAC |
| Polymarket Gamma API | Market metadata, resolved events | None |
| Open-Meteo forecast API | 51-member ensemble forecast | None |
| Open-Meteo archive API | ERA5 reanalysis (observed temps) | None |
| AWC METAR API | Real-time airport observations | None |
| Weather Underground | Settlement station (parsed from market rules) | None |

## Risks

- Tail bucket liquidity is thin ($10-50 depth at $0.03-0.15 prices)
- Polymarket silently changes settlement stations without announcement
- 10-second heartbeat timeout kills all open orders since Jan 2026
- 425 matching engine restart every Tue 7AM ET (~90s)
- Only 3 cities (NYC, London, Tokyo) have reliably active daily markets
- Backtest uses ~42% forecast-derived fallback prices for inactive markets

## Development

```bash
# Lint
ruff check pm_bot/

# Type check
mypy pm_bot/

# Test (977 tests, 90% coverage)
pytest tests/ -q

# Run with debug logging
pm-bot scan --cities "New York" --verbose
```

## License

MIT License. See [LICENSE](LICENSE) for details.

## Disclaimer

This software is for educational and research purposes only. Trading on prediction markets involves significant financial risk. Past backtest performance does not guarantee future results. The authors are not responsible for any financial losses incurred through use of this software.
