# Weather Trading Bot - Complete Implementation

## Overview

Complete Polymarket weather trading system with EMOS calibration, multi-model ensemble, and automated market scanning.

## New Modules

### Core Modules

| Module | Purpose |
|--------|---------|
| `core/emos.py` | EMOS (Ensemble Model Output Statistics) calibration |
| `core/ensemble.py` | Multi-model ensemble forecasts (GFS, ECMWF, ICON, GEM) |
| `core/city_selector.py` | Intelligent city selection based on competition/liquidity |

### Strategies

| Strategy | Description |
|----------|-------------|
| `emos_gopfan2` | EMOS-enhanced gopfan2 (model-validated tail buying) |
| `emos_forecast_arb` | EMOS-enhanced forecast arbitrage |

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/scan_markets.py` | Market scanner for opportunities |
| `scripts/train_emos.py` | EMOS calibration training |
| `scripts/trade_bot.py` | Complete trading bot |

## Quick Start

### 1. Scan Markets
```bash
# Scan all cities for opportunities
python -m pm_bot.scripts.scan_markets

# Scan specific cities
python -m pm_bot.scripts.scan_markets --cities "Chicago,Miami,Buenos Aires"

# Tail-only mode (gopfan2 style)
python -m pm_bot.scripts.scan_markets --mode tail --min-edge 0.08
```

### 2. Train EMOS Calibrators
```bash
# Train for single city
python -m pm_bot.scripts.train_emos --city "New York" --days 90

# Train for all cities
python -m pm_bot.scripts.train_emos --all-cities --days 60
```

### 3. Run Trading Bot
```bash
# Scan mode (default)
python -m pm_bot.scripts.trade_bot scan

# Paper trading mode
python -m pm_bot.scripts.trade_bot paper --bankroll 100

# With specific cities
python -m pm_bot.scripts.trade_bot scan --cities "Buenos Aires,Cape Town,Lagos"
```

## Strategy Details

### EMOS-Enhanced gopfan2

Combines gopfan2's proven price-threshold approach with EMOS calibration:

1. **Price Filter**: Only buckets with price < $0.15 (gopfan2 rule)
2. **Model Validation**: EMOS probability must be > 18%
3. **Sizing**: Quarter Kelly, $2 max per position

**Why better than pure gopfan2:**
- Pure gopfan2 buys all cheap buckets equally (some are correctly cheap)
- EMOS filter only buys cheap buckets where model says probability is higher
- Result: higher win rate, better risk-adjusted returns

### EMOS-Enhanced Forecast Arbitrage

Uses calibrated probabilities for more accurate edge calculation:

1. **Calibrated Probability**: EMOS-adjusted ensemble forecast
2. **Edge Detection**: Model probability vs market price
3. **Position Sizing**: Kelly criterion with quarter-Kelly safety

## EMOS Calibration

### What is EMOS?

EMOS (Ensemble Model Output Statistics) fixes ensemble underdispersion:

```
Raw ensemble: N(μ_ensemble, σ²_ensemble) — often underdispersive
EMOS calibrated: N(a + b·μ_ensemble, c + d·σ²_ensemble)
```

Coefficients (a, b, c, d) are trained on historical data by minimizing CRPS.

### Training Process

1. Collect historical ensemble forecasts and observations
2. Optimize coefficients to minimize CRPS
3. Save calibrated model for trading

### Usage

```python
from pm_bot.core.emos import EMOSCalibrator, bucket_probability_emos

# Load trained calibrator
calibrator = EMOSCalibrator.load("data/emos/emos_new_york.json")

# Calculate calibrated probability
ensemble = [20.0, 21.0, 22.0, 23.0, 24.0]
prob = bucket_probability_emos(calibrator, ensemble, 20.0, 22.0, "C")
```

## Multi-Model Ensemble

Combines forecasts from multiple weather models:

- **GFS** (NOAA) — 31 members
- **ECMWF IFS** — 51 members (most accurate)
- **ICON** (Germany) — 40 members
- **GEM** (Canada) — 20 members

Weighted average based on historical performance.

## City Selection

Automatically selects best cities for trading based on:

1. **Tail Buckets**: More buckets with price < $0.15
2. **Bot Competition**: Lower competition = more edge
3. **Liquidity**: Enough to fill orders

**Recommended cities (low competition):**
- Buenos Aires (ColdMath focus)
- Cape Town (ColdMath focus)
- Lagos
- Wellington
- Atlanta

## Backtesting

```bash
# Backtest EMOS vs raw strategies
python -m pm_bot.cli.scanner backtest-emos --city "New York" --days 30
```

## Risk Management

- **Max Position**: $2 per trade (gopfan2 style)
- **Kelly Fraction**: 0.25 (quarter Kelly)
- **Min Edge**: 8% for tail, 15% for arb
- **Max Exposure**: 70% of bankroll

## References

- [polymarket-tmax-lab](https://github.com/YoungseokOh/polymarket-tmax-lab) — EMOS implementation
- [gopfan2 strategy](https://polymarketweather.com/blog/gopfan2-polymarket) — $343K+ profit
- [ColdMath strategy](https://polymarketweather.com/blog/coldmath-polymarket) — $120K+ profit
- [Windfall](http://windfall.polsia.app/) — Edge detection tool
- [Degen Doppler](https://degendoppler.com/) — 14-model ensemble
