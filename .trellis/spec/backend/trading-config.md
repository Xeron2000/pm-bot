# Trading & Backtest Configuration

> Polymarket天气市场交易策略、踩坑记录、真实可行性分析。

---

## ⚠️ 核心教训：回测陷阱

### 踩坑1：P&L公式方向错误

**症状**：回测显示+57,000%回报，NO方向交易盈亏反转。

**原因**：NO方向P&L公式写反了：

```python
# ❌ 错误 (旧代码)
raw_pnl = size * effective_price if not hit else -size * (1.0 - effective_price)
# NO赢了拿到的是stake(你付的钱)，不是payout

# ✅ 正确 (已修复)
raw_pnl = size * (1.0 - effective_price) if not hit else -size * effective_price
# NO赢了拿到payout($1.00/份)，利润 = payout - cost
```

**修复位置**：`pm_bot/backtest/engine.py` 两处（run_real 和 run_portfolio）

**验证方法**：

```python
# NO at $0.990, bucket不发生(NO赢):
# 你付 $0.990/份, 赢了拿 $1.00/份, 利润 = $0.01/份
# raw_pnl = size * (1.0 - 0.990) = size * 0.01 ✓
```

---

### 踩坑2：用mid price成交

**症状**：回测假设你能以mid price成交，但Polymarket订单簿实际是：

```
YES bid=$0.010  YES ask=$0.990
NO  bid=$0.010  NO  ask=$0.990
mid = (0.010 + 0.990) / 2 = $0.500
```

**实际交易成本**：
| 操作 | 回测假设 | 实际成本 | 差距 |
|------|----------|----------|------|
| 买YES (mid=$0.30) | $0.30 | $0.990 | +230% |
| 买NO (mid=$0.80) | $0.80 | $0.990 | +24% |
| 买YES (mid=$0.01) | $0.01 | $0.010 | 0% ✓ |
| 买NO (mid=$0.99) | $0.99 | $0.990 | 0% ✓ |

**结论**：只有尾部桶 (mid < $0.15 或 > $0.85) 的价格是准确的。中部桶的回测结果完全不可信。

**修复**：添加 `spread_pct` 参数到 BacktestEngine，模拟真实订单簿。

---

### 踩坑3：Kelly sizing用mid price

**症状**：spread存在时Kelly sizing过高，因为payout被高估。

**原因**：

```python
# ❌ 用mid price算payout
kelly_size(edge=0.10, yes_price=0.30)  # payout = 0.70

# ✅ 用spread-adjusted price算payout
kelly_size(edge=0.10, yes_price=0.545) # payout = 0.455
```

**修复**：所有kelly_size调用改为传入effective_price而非rec.bucket.yes_price。

---

### 踩坑4：中部桶交易全部负EV

**原因**：Polymarket天气市场的订单簿结构使得中部桶不可能盈利：

- 买YES: 付$0.990 ask, 赢了赚$0.010, 输了亏$0.990
- 买NO: 付$0.990 ask, 赢了赚$0.010, 输了亏$0.990
- **风险回报比 99:1**，需要>99%胜率才能break even

**数据验证** (spread=0.99回测)：
| 策略 | 中部桶P&L | 中部桶胜率 |
|------|-----------|-----------|
| neg_risk_field_fade | -$7,386 | 0% |
| neg_risk_sum | -$10,606 | 0% |
| truncation_edge | -$20,037 | 0% |
| gopfan2 | -$6,498 | 0% |
| resolution_div | -$5,630 | 0% |
| ensemble_spread | -$6,493 | 0% |

**结论**：所有策略的中部桶交易都是负EV，必须排除。

---

## 修正后策略有效性分析

### ✅ 有效策略：尾部NO (neg_risk_field_fade核心)

**机制**：买极端温度桶的NO ($0.01/份)，赌极端温度不会发生。

**为什么有效**：

- 极端温度发生概率 <5% → NO胜率 >95%
- 赢了赚$0.99/份，输了亏$0.01/份
- 风险回报比 1:99，期望值极高

**数据** (spread=0.99, 365天, 9城市)：
| 策略 | 尾部NO笔数 | 尾部NO P&L | 胜率 |
|------|-----------|-----------|------|
| neg_risk_field_fade | 1,051 | +$99,275 | 95.5% |
| neg_risk_sum | 379 | +$34,694 | 92.6% |
| truncation_edge | 313 | +$28,665 | 92.7% |
| resolution_div | 74 | +$7,021 | 95.9% |

**执行问题**：

- 你挂$0.01买单买NO
- 谁会$0.01卖出NO？几乎没人（因为大家都知道NO大概率赢）
- **成交率极低 (<1%)**
- 理论EV高但实际赚不到钱

---

### ⚠️ 边际有效：尾部YES彩票

**机制**：买极端温度桶的YES ($0.01/份)，赌极端温度会发生。

**为什么边际可行**：

- 极端温度发生概率 3-5% → YES胜率 3-5%
- 赢了赚$0.99/份，输了亏$0.01/份
- EV(5%) = 0.05 × $0.99 - 0.95 × $0.01 = **+$0.04/份**
- EV(3%) = 0.03 × $0.99 - 0.97 × $0.01 = **+$0.02/份**

**执行可行性**：

- 有人愿意$0.01卖出YES（因为95%概率变废纸）
- 成交率可能 20-30%
- 但EV太低，每份只赚$0.02-0.04

**实际收益估算**：

```
34城市 × 2尾部桶 = 68个挂单/天
30%成交率 = 20笔/天
4%中奖率 = 0.8笔赢/天
日利润 = 0.8 × $0.99 - 19.2 × $0.01 = $0.60/天
年化 = ~$219 (从$1000起始, ~22%回报)
```

---

### ❌ 无效策略：所有中部桶交易

**原因**：Polymarket订单簿bid=$0.010/ask=$0.990，中部桶只能以$0.990买入，风险回报比99:1。

**受影响的策略**：

- gopfan2 的 NO mid-bucket trades
- neg_risk_field_fade 的 mid-bucket trades
- neg_risk_sum 的 mid-bucket trades
- truncation_edge 的 mid-bucket trades
- ensemble_spread 的所有 trades
- resolution_div 的 mid-bucket trades

---

## CLI参数

```
pm-bot backtest [OPTIONS]
  --spread FLOAT   真实价差: 买入价 = mid + spread/2 (e.g. 0.49 for Polymarket)
                   尾部桶 (mid<0.15或>0.85): 入场价 = $0.01 (bid)
                   中部桶: 入场价 = spread_pct (默认 $0.99 ask)
```

---

## 策略排名 (修正后, spread=0.99)

| 策略                | 总P&L    | 尾部NO P&L | 尾部YES P&L | 中部桶 P&L | 有效性            |
| ------------------- | -------- | ---------- | ----------- | ---------- | ----------------- |
| neg_risk_field_fade | +$91,889 | +$99,275   | $0          | -$7,386    | ⭐ 最强           |
| neg_risk_sum        | +$24,356 | +$34,694   | +$267       | -$10,606   | ⭐ 强             |
| truncation_edge     | +$16,433 | +$28,665   | +$7,805     | -$20,037   | ⚠️ 中部桶拖累严重 |
| gopfan2             | +$906    | $0         | +$7,405     | -$6,498    | ⚠️ 仅尾部YES微利  |
| resolution_div      | +$2,908  | +$7,021    | +$1,518     | -$5,630    | ⚠️ 中部桶拖累     |
| ensemble_spread     | -$11     | $0         | +$6,481     | -$6,493    | ❌ 不可用         |

---

## 最佳组合策略

### neg_risk_field_fade + neg_risk_sum

- 两者都主要做尾部NO交易
- neg_risk_field_fade: 当ΣYES > 1.02时，买最贵桶的NO
- neg_risk_sum: 当ΣYES < 0.98时买YES，> 1.03时买NO
- 合计尾部NO P&L: **+$133,969**
- 但执行可行性低（成交率<1%）

### 实盘建议

1. **不要做中部桶交易** — 全部负EV
2. **尾部YES彩票** — 唯一有正EV且可能成交的策略
3. **尾部NO挂单** — EV很高但几乎无法成交
4. **真正的edge来自信息优势** — 更快更准的温度预报

---

## Polymarket Weather City Universe (36 cities)

### Tier 1 — Very High Liquidity ($6M+)

Hong Kong, Shanghai, NYC, Tokyo, Beijing, London

### Tier 2 — High Liquidity ($3–5M)

Madrid, Taipei, Seoul, Wellington, Miami, LA, Chicago, Milan, Paris, Wuhan, Denver, Munich, Austin, Moscow, Warsaw, San Francisco

### Tier 3 — Medium Liquidity ($2–3M)

Istanbul, Jakarta, Mexico City, Atlanta, Dallas, Amsterdam, Busan, Seattle, Helsinki, Lagos, Toronto, Buenos Aires, Cape Town

---

## 参数范围

| 参数      | 推荐值   | 说明                          |
| --------- | -------- | ----------------------------- |
| kelly     | 0.25     | 影响很小（max_pos限制了仓位） |
| stop_loss | 0.85     | 略紧于0.90，释放资金更快      |
| max_pos   | 10%      | 单仓上限                      |
| spread    | 0.99     | 模拟真实订单簿                |
| cities    | 34个全部 | 最大化市场覆盖                |

---

## 未来改进方向

1. **实时温度预报集成** — 接入GFS/ECMWF/HRRR，获取信息优势
2. **订单簿深度数据** — 用Polymeteo API获取真实L2数据，精确模拟成交
3. **时间窗口策略** — 在模型更新后30秒内下单，捕获价格发现窗口
4. **做市策略** — 在bid/ask之间挂单，赚spread（需要大量资金）
5. **跨市场套利** — 同一城市不同日期的市场定价不一致
