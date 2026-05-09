# Trading & Backtest Configuration

> Polymarket 天气市场交易策略、踩坑记录、真实可行性分析。

---

## ⚠️ 核心教训：回测陷阱

### 踩坑1：P&L 公式方向错误

**症状**：回测显示 +57,000% 回报，NO 方向交易盈亏反转。

**原因**：NO 方向 P&L 公式写反了：

```python
# ❌ 错误 (旧代码)
raw_pnl = size * effective_price if not hit else -size * (1.0 - effective_price)

# ✅ 正确 (已修复)
raw_pnl = size * (1.0 - effective_price) if not hit else -size * effective_price
```

### 踩坑2：用 mid price 成交

Polymarket 订单簿实际是 bid=$0.010/ask=$0.990，mid=$0.500。只有尾部桶 (mid < $0.15 或 > $0.85) 的价格是准确的。中部桶回测结果完全不可信。

### 踩坑3：中部桶交易全部负EV

买 YES 付 $0.990 ask，赢了赚 $0.010，输了亏 $0.990。风险回报比 99:1，需要 >99% 胜率才能 break even。

---

## 当前策略：gopfan2 (尾部YES彩票)

### 机制

买极端温度桶的 YES ($0.01/份)，赌极端温度会发生。

### 条件

```python
# 在 strategies/base.py Gopfan2Strategy.run()
if b.yes_price <= yes_max:  # 默认 0.15
    model_prob = bucket_probability_numpy(forecast, b.temp_low_c, b.temp_high_c)
    if model_prob > b.yes_price + 0.02:  # edge > 2%
        edge = model_prob - b.yes_price
```

### 为什么可行

- 极端温度发生概率 3-5% → YES 胜率 3-5%
- 赢了赚 $0.99/份，输了亏 $0.01/份
- EV(5%) = 0.05 × $0.99 - 0.95 × $0.01 = **+$0.04/份**
- 有人愿意 $0.01 卖出 YES（因为 95% 概率变废纸）
- 成交率可能 20-30%

### 已删除策略 (2026-05-07)

| 策略 | 删除原因 |
|------|----------|
| neg_risk_field_fade | 核心是尾部NO，live fill rate <1% |
| neg_risk_sum | 核心是尾部NO，live fill rate <1% |
| truncation_edge | 中部桶交易全部负EV |
| ensemble_spread | 总P&L为负 |
| resolution_div | 中部桶交易全部负EV |

---

## 关键参数

| 参数 | 当前值 | 说明 |
|------|--------|------|
| kelly_multiplier | 0.10 | 10% fractional Kelly，对未校准模型更安全 |
| yes_max | 0.15 | 只交易 ≤$0.15 的尾部桶 |
| min_edge | 0.08 | live 模式最低 8% edge |
| max_single | $50 | 单笔上限 |
| max_daily | $200 | 日上限 |
| max_total_pct | 30% | 总暴露占 bankroll 比例 |
| stop_loss | 可配置 | 建议 0.20 (20%) |
| WARMUP_DAYS | 30 | Station bias EMA warmup 天数 |
| GEFS members | 31 | GFS 集合预报成员数 |
| RESOLVED_THRESHOLD | 0.90 | 判断市场 resolved 的 outcomePrices 阈值 |

---

## Station Bias 修正系统

### 机制

EMA (指数移动平均) 追踪每个站点的预报偏差：

```python
# station_bias.py
bias_c = alpha * error + (1.0 - alpha) * bias_c  # alpha=0.15
```

### Prior Bias (先验偏差)

在 warmup 期间（30 天），使用 ERA5 冷偏差先验值：

| 站点 | 先验偏差 (°C) |
|------|--------------|
| New York | 0.7 |
| London | 0.8 |
| Tokyo | 0.8 |
| Seoul | 0.9 |
| Shanghai | 0.9 |
| Beijing | 0.9 |
| Hong Kong | 0.5 |
| Miami | 0.6 |
| Dallas | 1.1 |
| Paris | 0.7 |

warmup 完成后，EMA 偏差覆盖先验值。

---

## 概率模型

### GEFS 集合预报

- 31 个 GFS 集合成员 (member00-member30)
- 直接统计法：桶概率 = 落在桶内的成员数 / 31
- 不足：GEFS ensemble 通常欠散 20-40%

### Gaussian CDF 回退

当 ensemble 不可用时：

```python
std = forecast.std if forecast.std > 0.5 else 2.5
z = (temp - mean) / std
p = 0.5 * (1 + erf(z / sqrt(2)))
```

### BMA 共识

跨源加权：Open-Meteo + NWS + METAR

```python
inv_sq = [1.0 / max(s.std**2, 0.01) for s in sources]
weights = [w / total for w in inv_sq]
```

---

## 回测引擎

### 三种模式

1. **run()** — 合成回测，用 Open-Meteo 预报 + archive 观测
2. **run_real()** — 真实 CLOB 价格回测
3. **run_portfolio()** — 组合模式，所有策略共享 bankroll

### 费用模型

| 费用 | 值 | 说明 |
|------|-----|------|
| Taker fee | 50bps (capped at 1.25%) | v2 规则 |
| Maker fee | 0% | 限价单免费 |
| Slippage | 1% | 默认 |
| Stop loss slippage | 3% | 止损时额外滑点 |
| Ghost trade loss | 2% | live 模式 |
| Tail price penalty | 5% | $0.01-$0.15 价格 |
| Forecast penalty | 5% | 预报派生价格 |

### Fill Model

```python
fill_prob_at_best = 0.50  # mid 价格
fill_prob_inside = 0.25   # 优于 mid
fill_prob_tail = 0.10     # 尾部价格 ($0.01 或 $0.99)
```

### Metrics

- **Sharpe**: 年化 (sqrt(365))，Bessel 校正 (n-1)
- **Sortino**: downside variance 除以总观测数
- **Max Drawdown**: bankroll series 峰谷比
- **Brier Score**: bucket_hit 或 PnL 符号作为 outcome proxy

---

## Polymarket Weather City Universe (36 cities)

### Tier 1 — Very High Liquidity ($6M+)

Hong Kong, Shanghai, NYC, Tokyo, Beijing, London

### Tier 2 — High Liquidity ($3–5M)

Madrid, Taipei, Seoul, Wellington, Miami, LA, Chicago, Milan, Paris, Wuhan, Denver, Munich, Austin, Moscow, Warsaw, San Francisco

### Tier 3 — Medium Liquidity ($2–3M)

Istanbul, Jakarta, Mexico City, Atlanta, Dallas, Amsterdam, Busan, Seattle, Helsinki, Lagos, Toronto, Buenos Aires, Cape Town

---

## CLI 参数

```
pm-bot backtest [OPTIONS]
  --strategy STR    策略名 (gopfan2)
  --bankroll FLOAT  起始资金 (默认 100)
  --days INT        回测天数 (默认 90)
  --kelly FLOAT     Kelly fraction (默认 0.10)
  --stop-loss FLOAT 止损比例 (默认 0.0)
  --spread FLOAT    真实价差 (默认 0.0)
  --live            Live-trading 模式
  --portfolio       组合模式
  --real            使用真实 CLOB 历史价格
  --csv PATH        导出 CSV
```

---

## 未来改进方向

1. **Out-of-sample 验证** — 拆分 train/test 数据，验证策略泛化能力
2. **Reliability diagram** — 检查概率校准，计算 Brier score decomposition
3. **实时温度预报集成** — 接入 ECMWF ensemble，获取更多集合成员
4. **订单簿深度数据** — 用 Polymeteo API 获取真实 L2 数据，精确模拟成交
5. **时间窗口策略** — 在模型更新后 30 秒内下单，捕获价格发现窗口
6. **NO 策略重新开发** — 在解决成交率问题后，重新引入尾部 NO 策略
7. **自适应 BMA 权重** — 用历史预报-观测对动态校准模型权重
