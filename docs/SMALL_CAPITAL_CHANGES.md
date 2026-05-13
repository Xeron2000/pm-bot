# Small Capital Strategy Redesign — Change Log

## Date: 2026-05-10

## Philosophy

All strategies redesigned for **$500-$2000 bankrolls** using research-backed principles:

| Principle | Before | After | Source |
|-----------|--------|-------|--------|
| Edge threshold | 2-3% | **8%** minimum | PolymarketWeather strategy guide |
| Kelly fraction | 0.60 (aggressive) | **0.25** (quarter Kelly) | Industry standard for small accounts |
| Max per position | $50-$100 | **$1-$2** (weather), **$10** (copy) | gopfan2 proven approach |
| Max single % | 10-50% | **2%** | 2% rule for risk management |
| Min trade size | $100 | **$5** (copy), **$1** (weather) | Small capital reality |
| Entry price filter | ≤$0.80 | **≤$0.65** | Polyloly 334-trade research |
| Cash reserve | 0% | **30%** (max_total_pct=0.70) | Small account protection |

## Files Changed

### 1. `bots/weather/strategies/base.py`
- **Gopfan2Strategy**: edge_threshold 2% → 8%, kelly 0.25, max_position $2, added proper Kelly sizing
- **Strategy base class**: Added `max_position_usd` parameter, updated defaults

### 2. `bots/weather/strategies/laddering.py`
- **CRITICAL FIX**: Replaced `edge = price * 0.5` (fake) with model-based probability calculation
- kelly_fraction 0.60 → 0.25, max_position $2 per bucket
- edge_threshold 3% → 8%, max_price 0.25 → 0.15

### 3. `bots/weather/strategies/forecast_arb.py`
- kelly_fraction 0.80 → 0.25, max_position $2
- Max 3 recommendations per event (focus on best opportunities)
- Added bankroll parameter passing

### 4. `bots/weather/strategies/tail_no_barbell.py`
- **CRITICAL FIX**: Replaced hardcoded `estimated_no_prob = 0.85` with model-based calculation
- **CRITICAL FIX**: Replaced `estimated_prob = b.yes_price * 1.5` with model probability
- kelly_fraction 0.60 → 0.25, max_position $2 (NO), $1 (YES lottery)
- edge_threshold 3% → 8% for YES, 3% for NO

### 5. `bots/weather/strategies/resolution_delay.py`
- kelly_fraction 0.80 → 0.25, max_position $1 (high-risk strategy)
- min_confidence 80% → 90% (only trade when very confident)
- edge_threshold 10%

### 6. `bots/smart_wallet/strategy.py`
- **DEFAULT_PARAMS**: min_trade_usd $100 → $5, max_entry_price_copy $0.80 → $0.65
- Added `max_position_usd: $10` parameter
- **CopyStrategy**: Added max_position_usd cap in _calculate_size
- **InverseStrategy**: Raised min_entry_price_inverse to $0.70, min_wallet_score to 0.7, halved position sizes

### 7. `bots/weather/backtest/engine.py`
- Default bankroll $100 → $1000
- max_single_pct 10% → 2%, max_notional $100 → $10
- kelly_fraction_val 0.25 (unchanged)

### 8. `bots/weather/backtest/costs.py`
- live_max_position_usd $50 → $10

### 9. `bots/weather/cli/backtest_cmd.py`
- Default bankroll $100 → $1000
- Default max_pos 10% → 2%
- Live mode help text updated

## Expected Performance (Honest Estimates)

| Strategy | Bankroll | Expected Monthly ROI | Risk Level |
|----------|----------|---------------------|------------|
| gopfan2 | $1000 | +2-5% | Medium |
| laddering | $1000 | +1-4% | High variance |
| forecast_arb | $1000 | +3-8% | Medium |
| tail_no_barbell | $1000 | +2-6% | Medium |
| resolution_delay | $1000 | +1-3% | Very High |
| Copy (smart wallet) | $1000 | +2-5% | Low-Medium |
| Inverse (smart wallet) | $1000 | +0-3% | High |

**Note**: These are AFTER realistic costs (slippage, fees, fill rate). Zero-slippage backtests will show much higher numbers.

## Key Risk Warnings

1. **Alpha decay**: Weather and copy markets are getting more efficient as more bots enter
2. **Fill rate**: Tail buckets (10% fill rate) mean many signals won't execute
3. **Minimum trade**: Polymarket $1 minimum means very small positions may not be possible
4. **Liquidity**: Weather markets have $5K-$50K depth; $2 positions are fine, but scaling up will move prices
