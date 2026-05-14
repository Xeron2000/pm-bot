---
scope: backend
---

# PM-Bot 资金管理规范

## 概述

保守资金管理模式，适用于 $100-$2000 小资金 Polymarket 天气交易。

## 风险态度

- **风险等级**: 低-中（保守 Kelly）
- **目标**: 长期正期望值，不追求快速翻倍
- **破产概率目标**: <5%

## 核心策略 (2 个)

### 1. gopfan2 (尾部YES彩票)

- **逻辑**: 买低价YES尾部桶 ($0.01-$0.15)，需要模型验证 edge ≥ 8%
- **胜率**: ~3-5%
- **赔率**: 1:6 到 1:99
- **Kelly**: 0.25 (quarter Kelly)
- **Max position**: $2

### 2. forecast_arb (预报套利)

- **逻辑**: 模型与市场价格差距 >15% 时建仓
- **Kelly**: 0.25 (quarter Kelly)
- **Max position**: $2
- **Max per event**: 3 recommendations

## 仓位管理

| 参数 | 值 | 说明 |
|------|-----|------|
| kelly_fraction | 0.25 | Quarter Kelly |
| max_single_pct | 0.02 | 单笔最大 2% bankroll |
| max_position_usd | $2 | 单笔上限 |
| max_total_pct | 70% | 总暴露（30% 现金储备） |

## 费用模型 (Polymarket Weather)

| 价格区间 | Taker费率 |
|----------|----------|
| 5¢ (tail) | 0.24% |
| 10¢ | 0.45% |
| 20¢ | 0.80% |
| 50¢ | 2.50% |

tail 桶费率极低，适合高频小额交易。

## 禁止行为

- Kelly > 0.30 用于未校准模型
- max_single_pct > 0.05
- 使用已被证明负EV的策略
- 不做回测就实盘
- 用 mid price 做中部桶交易

## 已删除的激进模式

$100 Aggressive Mode（kelly=0.60-0.80, max_single_pct=0.50-0.60）已于 2026-05-14 删除。
原因：破产概率过高，多个策略本身也已删除。

---

**最后更新**: 2026-05-14
