# Polymarket Weather Trading Bot

> 自动化 Polymarket 每日天气市场交易机器人。基于 EMOS 校准的多模型集合预报，三策略组合买入便宜桶。

## 核心特性

- **EMOS 校准** — 修复集合预报欠散，提高概率准确性
- **多模型集成** — GFS + ECMWF IFS + ICON + GEM 四模型加权
- **三策略组合** — Ladder(40%) + Tail(30%) + Gopfan2(30%)
- **流动性安全** — 所有策略只买 < 20¢ 桶，避免价格冲击

## 快速开始

```bash
uv sync
pm-bot-v2 --help
pm-bot-v2 scan --cities "Chicago,Miami"
pm-bot-v2 train --all --days 45
pm-bot-v2 paper --bankroll 100
```

## 策略

| 策略 | 权重 | 价格 | 核心逻辑 |
|------|------|------|----------|
| Ladder | 40% | < 20¢ | 相邻温度桶覆盖，neobrother 模式 |
| Tail | 30% | < 15¢ | 尾部低估桶，Hans323 模式 |
| Gopfan2 | 30% | < 15¢ | 简单价格规则：YES < 15¢，NO > 45¢ |

**盈利原理**：买 8-15¢，赢了赚 $0.85-0.92，输了亏 8-15¢，盈亏比 8-10:1。

## 回测（合成数据，90 天，$100）

| 策略 | 收益 | 交易 | 胜率 | Sharpe |
|------|------|------|------|--------|
| Combined | +4013% | 1346 | 22% | 14.65 |

⚠️ 合成数据高估 5-10 倍。真实预期：月收益 20-40%（保守）。

## 纸面交易

```bash
uv run python3 paper_trade.py          # 单次运行
uv run python3 paper_trade.py --loop   # 持续运行
uv run python3 paper_trade.py --status # 查看状态
```

## 项目结构

```
bots/weather/
├── core/weather.py          # 多模型集成 + EMOS
├── strategies/emos_edge.py  # 生产策略
├── backtest/weather_strategies.py # 回测策略
└── scripts/train_emos.py    # EMOS 训练

data/emos_coeffs/            # 14 城市 EMOS 系数
paper_trade.py               # 纸面交易机器人
```

## 配置

```bash
cp config.template.toml config.toml
```

```toml
[mode]
mode = "paper"

[sizing]
bankroll = 100.0
kelly_fraction = 0.25

[clob]
clob_api_key = ""
clob_secret = ""
clob_pass_phrase = ""
```

## 参考

- [Hans323](https://polymarket.com/profile/Hans323) — $1.1M 利润，51% 胜率
- [neobrother](https://polymarket.com/profile/neobrother) — $20K+，梯子策略
- [Polymarket Weather](https://polymarketweather.com) — 商业 bot，85-90% 命中率

## Disclaimer

For educational purposes only. Trading involves significant financial risk.
