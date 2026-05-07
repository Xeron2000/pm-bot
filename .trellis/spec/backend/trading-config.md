# Trading & Backtest Configuration

> Optimal parameter ranges, city universe, and strategy configuration for pm-bot.

---

## Scenario: Backtest & Live Trading Parameter Configuration

### 1. Scope / Trigger
- Any change to backtest parameters (bankroll, kelly, stop-loss, cities, strategy selection)
- Any change to live daemon configuration
- Adding/removing cities from the weather universe

### 2. Signatures

```
# CLI
pm-bot backtest [OPTIONS]
  --strategy/-s TEXT         Strategy name or comma-separated (omit for --all)
  --all                      Run all strategies
  --compare                  Side-by-side comparison
  --portfolio                Portfolio mode (all strategies share bankroll)
  --bankroll/-b FLOAT        Starting bankroll USD [default: 100.0]
  --days/-d INTEGER          Days to backtest [default: 90]
  --cities/-c TEXT           Comma-separated cities [default: NYC]
  --real                     Use real Polymarket historical prices
  --live                     Live-trading mode (maker-only, $50/pos, 8%+ edge)
  --stop-loss FLOAT          Stop-loss as fraction [default: 0.0]
  --kelly FLOAT              Kelly fraction [default: 0.25]
  --max-pos FLOAT            Max single position as fraction of bankroll [default: 0.10]
  --no-compound              Disable compounding
  --compare-forecast         Dual-run: all vs CLOB-only
  --forecast-penalty FLOAT   Conservative penalty for forecast prices [default: 0.05]
  --seed INTEGER             Random seed for FillModel

# Daemon config (config.toml)
[daemon]
cities = ["NYC","London","Tokyo",...]
scan_interval = 300

[sizing]
bankroll = 500.0
kelly_fraction = 0.25
stop_loss = 0.0
max_single = 50.0
max_daily = 200.0
max_per_city = 100.0
max_total_pct = 0.30
```

### 3. Contracts

| Parameter | Type | Constraint | Default | Notes |
|-----------|------|-----------|---------|-------|
| bankroll | float | > 0 | 100.0 | Starting capital in USD |
| kelly | float | 0.01–1.0 | 0.25 | Fraction of Kelly criterion |
| stop_loss | float | 0.0–1.0 | 0.0 | 0 = disabled, 0.85 = exit at 15% drawdown |
| max_pos | float | 0.01–1.0 | 0.10 | Max single position as fraction of bankroll |
| days | int | 1–365 | 90 | Backtest lookback window |
| cities | list[str] | city names | DEFAULT_CITIES | Must exist in CITY_COORDS |
| seed | int | any | None | Deterministic FillModel sampling |

**City Validation Contract**:
- Every city in `--cities` must resolve via `resolve_city_alias()` to a key in `CITY_COORDS`
- Unknown city → logged warning, skipped (not error)
- Alias resolution: NYC→New York, LA→Los Angeles, HK→Hong Kong, SP→São Paulo, SF→San Francisco, CDMX→Mexico City

### 4. Validation & Error Matrix

| Condition | Behavior |
|-----------|----------|
| Unknown strategy name | Print error + available names, exit |
| City not in CITY_COORDS | Log warning, skip city |
| bankroll ≤ 0 | CLI validation error |
| kelly > 1.0 | CLI validation error |
| stop_loss > 1.0 | CLI validation error |
| --live without --real | Auto-implies --real |
| --portfolio without --real | Portfolio mode only for real data |
| --compare-forecast without --real | Ignored (no forecast prices in synthetic mode) |

### 5. Good / Base / Bad Cases

**Good** (recommended production config):
```bash
pm-bot backtest --portfolio --real --days 365 --bankroll 1000 \
  --cities "New York,London,Tokyo,Chicago,Miami,Seoul,Warsaw,Lagos,Hong Kong,Paris,Taipei,Denver,Austin,Helsinki,Shanghai,Beijing,Madrid,Istanbul,Moscow,San Francisco,Amsterdam,Wellington,Milan,Wuhan,Munich,Jakarta,Mexico City,Atlanta,Dallas,Busan,Seattle,Toronto,Cape Town,São Paulo,Buenos Aires" \
  --stop-loss 0.85 --kelly 0.25 --max-pos 0.10 --seed 42
```

**Base** (quick test):
```bash
pm-bot backtest --all --compare --real --days 90 --bankroll 100 \
  --cities "New York,London,Tokyo" --kelly 0.25 --max-pos 0.10
```

**Bad** (do NOT do):
```bash
# Don't: live mode with no real data
pm-bot backtest --live --days 90

# Don't: kelly > 0.5 with max_pos > 0.15 (excessive risk)
pm-bot backtest --kelly 1.0 --max-pos 0.30

# Don't: single city only (insufficient diversification)
pm-bot backtest --portfolio --real --cities "NYC"
```

### 6. Tests Required

| Test | Assertion |
|------|-----------|
| All 36 cities resolve to coords | `assert all(resolve_city_alias(c) in CITY_COORDS for c in all_cities)` |
| Portfolio mode returns single result | `assert len(results) == 1` |
| Stop-loss 0.85 produces tighter MaxDD than 0.90 | `assert maxdd_085 <= maxdd_090` |
| Kelly 0.10–0.50 produce similar returns (position capped) | `assert abs(ret_010 - ret_050) / ret_010 < 0.05` |
| 34-city return > 9-city return | `assert ret_34cities > ret_9cities` |
| Live mode (8% min edge) produces 0 trades | `assert live_trades == 0` (documented gap) |

### 7. Wrong vs Correct

#### Wrong
```python
# Using only 9 cities and expecting good live returns
engine = BacktestEngine(
    strategies=strats,
    cities=["NYC", "London", "Tokyo"],  # Too few
    live_mode=True,  # 8% min edge filter
)
# Result: 0 trades in live mode
```

#### Correct
```python
# Use all 34 cities, portfolio mode, realistic stop-loss
engine = BacktestEngine(
    strategies=list(get_all_strategies().values()),
    cities=ALL_34_CITIES,
    bankroll=1000,
    kelly_fraction_val=0.25,
    max_single_pct=0.10,
    stop_loss_pct=0.85,
    live_mode=False,  # Until live-mode gap is resolved
)
result = await engine.run_portfolio()
# Result: +57,102% return, Sharpe 5.00, 16,676 trades
```

---

## Strategy Ranking (365-day, 34-city real data)

| Strategy | Return% | Sharpe | Win% | MaxDD | Trades | Best For |
|----------|---------|--------|------|-------|--------|----------|
| neg_risk_field_fade | +53,710% | 5.04 | 79.8% | 0.3% | 9,981 | Highest return + win rate |
| neg_risk_sum | +32,027% | 5.28 | 69.8% | 0.6% | 7,767 | Highest Sharpe |
| truncation_edge | +33,644% | 4.77 | 47.8% | 1.0% | 12,647 | Highest volume |
| gopfan2 | +29,181% | 4.78 | 47.5% | 1.1% | 11,053 | Consistent performer |
| ensemble_spread | +16,152% | 4.58 | 39.9% | 1.8% | 9,075 | Best signal filtering |
| resolution_div | +6,262% | 4.90 | 42.6% | 4.3% | 2,462 | Highest per-trade avg |

---

## Optimal Parameter Ranges (from sensitivity analysis)

### Kelly Fraction (minimal impact due to max_pos cap)
- Range: 0.10–0.50 (all produce similar returns)
- Recommended: **0.25** (conservative, stable)
- Note: Higher Kelly slightly improves Sortino but has no material effect on return

### Stop-Loss Level
- Tighter SL (0.80–0.85) **slightly increases returns** and improves MaxDD
- Recommended: **0.85** (exits losing positions faster, frees capital)
- No SL: acceptable but higher drawdown

### Max Position
- Recommended: **10%** of bankroll
- Higher (15–20%) acceptable for smaller bankrolls
- Never exceed 30% single position

---

## Polymarket Weather City Universe (36 cities)

### Tier 1 — Very High Liquidity ($6M+ / 50 events)
Hong Kong, Shanghai, NYC, Tokyo, Beijing, London

### Tier 2 — High Liquidity ($3–5M)
Madrid, Taipei, Seoul, Wellington, Miami, LA, Chicago, Milan, Paris, Wuhan, Denver, Munich, Austin, Moscow, Warsaw, San Francisco

### Tier 3 — Medium Liquidity ($2–3M)
Istanbul, Jakarta, Mexico City, Atlanta, Dallas, Amsterdam, Busan, Seattle, Helsinki, Lagos, Toronto, Buenos Aires, Cape Town

---

## Live↔Backtest Fidelity Gap

**Critical Issue**: Live mode (maker-only, 8% min edge, $50/pos cap, 2% ghost trade loss) produces **0 trades**.

**Root Cause**: The combination of:
- `live_min_edge = 0.08` (8% minimum edge threshold)
- `live_side = "maker"` (only passive limit orders)
- `live_max_position_usd = 50.0` ($50 per position cap)
- `ghost_trade_loss_pct = 0.02` (2% phantom loss)
- `tail_price_penalty_pct = 0.05` (5% tail price penalty)

**Resolution Needed** (future work):
1. Lower min_edge threshold to 3–5%
2. Allow taker fills with realistic slippage
3. Implement adaptive edge thresholds based on market conditions
4. Calibrate FillModel against actual Polymarket fill data
