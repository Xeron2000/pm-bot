# journal-2: $100 资金适配审计

**日期**: 2026-05-09
**阶段**: Phase 1 审计完成

## 审计结果

### 现状
- **活跃策略**: 仅 gopfan2 (尾部YES彩票)
- **已删除**: 5个策略 (neg_risk_field_fade, neg_risk_sum, truncation_edge, ensemble_spread, resolution_div)
- **删除原因**: 中部桶负EV + 尾部桶 fill rate <1%

### $100 关键发现

| 发现 | 影响 |
|------|------|
| 仅1个策略存活 | 无法分散风险, 复利路径单一 |
| gopfan2 年化 ~22% | $100→$122/年, 太慢 |
| 费用占交易额 ~13.5% | 需要 edge >15% 才有正EV |
| 仓位管理太保守 | max 10% single, 30% total 对$100太紧 |
| 缺少蒙特卡洛 | 无法评估破产概率 |
| 缺少雪球指标 | 无法衡量复利效率 |

### 优化方向

1. **激进仓位管理**: 允许 20-80% 单笔 (从10%提升)
2. **蒙特卡洛压力测试**: 1000+ 路径模拟, 计算破产概率
3. **高赔率策略**: 长尾桶 YES price $0.01-$0.05, 赔率 20:1 到 99:1
4. **Laddering**: 同时买多个尾部桶, 分散风险
5. **$100 专用指标**: 破产概率/雪球倍数/生存期

### 更新
- `config.toml`: 新增 `aggressive_100` 模式配置
- `tasks/05-09-100-dollar-audit/audit-report.md`: 完整审计报告
- 下一步: Phase 2 回测引擎强化

---

## 关键决策

**接受的风险**:
- 30-100% 日波动
- 50% 破产概率
- 单日可能亏50-80%

**不接受的风险**:
- 不做任何改变 (龟速复利)
- 使用已被证明负EV的策略
- 忽略费用侵蚀

---

**下次更新**: Phase 2 回测引擎强化完成后


## Session 18: 00 Aggressive Snowball - Monte Carlo + 5 Strategies

**Date**: 2026-05-10
**Task**: 00 Aggressive Snowball - Monte Carlo + 5 Strategies
**Branch**: `main`

### Summary

Implemented Monte Carlo simulator, snowball metrics, 5 high-conviction strategies (gopfan2, laddering, tail_no_barbell, forecast_arb, resolution_delay), one-click runner, and practical guide. Backtest: 00→52 in 60 days (+152%). All 36 tests passing.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `4557bfc` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 19: Smart wallet bot + project restructure

**Date**: 2026-05-10
**Task**: Smart wallet bot + project restructure
**Branch**: `main`

### Summary

Built complete Polymarket smart wallet copy-trading bot (Copy + Inverse strategies) with backtesting framework, slippage/latency models, and evidence chain documentation. Reorganized project into bot collection structure: bots/weather/, bots/smart_wallet/, shared/, docs/.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `e401c58` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 20: City variance filtering + commit cleanup

**Date**: 2026-05-13
**Task**: City variance filtering + commit cleanup
**Branch**: `main`

### Summary

Implemented city variance filtering (core/city_variance.py, CLI pm-bot variance, integrated into scan/watch/daemon). Committed near-certain bond strategy, staged entry, and related changes. Added docs and gitignored legacy pm_bot/.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `0b4004d` | (see git log) |
| `579bfca` | (see git log) |
| `75ea019` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 21: Code review fixes — config alignment, edge semantics, dead code cleanup

**Date**: 2026-05-13
**Task**: Code review fixes — config alignment, edge semantics, dead code cleanup
**Branch**: `main`

### Summary

Deep code review found 5 issues: (1) STRATEGY_DEFAULTS kelly_fraction never applied — fixed by passing config to constructors with **kwargs. (2) Resolution delay edge used price_gap instead of model-based — fixed to confidence - price. (3) Staged entry dead code — integrated into daemon. (4) City variance missing in trade.py — added. (5) Dead config keys (min_model_prob unimplemented, stale_hours removed). All 111 tests pass.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `42e378e` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 22: Project audit: prune dead strategies, fix Kelly params

**Date**: 2026-05-14
**Task**: Project audit: prune dead strategies, fix Kelly params
**Branch**: `main`

### Summary

Full project audit based on web research. Deleted 4 unprofitable strategies (tail_no_barbell, laddering, resolution_delay, near_certain_bond), deleted smart_wallet bot (no trade execution), fixed dangerous Kelly params (0.80→0.25), kept gopfan2 + forecast_arb as core strategies.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `342eee1` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 23: Research real backtest data pipeline, update specs

**Date**: 2026-05-14
**Task**: Research real backtest data pipeline, update specs
**Branch**: `main`

### Summary

Researched Polymarket CLOB prices-history API, Open-Meteo historical-forecast-api, EMOS calibration best practices. Updated trading-config spec with full data pipeline architecture and open-source references (polymarket-tmax-lab, PolyWeather, IMPROVER). Updated 100-dollar spec to conservative mode.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `ca86b25` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
