# Polymarket Weather Trading Bot

> 自动化 Polymarket 每日天气市场交易机器人。基于集合天气预报的模型 vs 市场定价偏差策略。

## 核心策略

**forecast_arb** — 利用 Open-Meteo GEFS 31 成员集合预报计算真实概率，与 Polymarket 市场价格比较。当 mispricing ≥ 15% 时，用 Kelly criterion 建仓。

## 快速开始

```bash
# 安装
uv sync

# 扫描市场机会
pm-bot scan --cities "New York,London,Tokyo"

# 实时监控（WebSocket）
pm-bot watch --interval 30

# 回测
pm-bot backtest --days 90 --bankroll 100 --live

# 纸面交易（无需 API Key）
pm-bot trade --dry-run

# 实盘交易
pm-bot trade --confirm
```

## 项目结构

```
pm/
├── bots/weather/
│   ├── core/              # 核心模块
│   │   ├── weather.py     # Open-Meteo 集合预报
│   │   ├── clob.py        # Polymarket CLOB 交易
│   │   ├── risk.py        # 熔断器 + 仓位限额
│   │   ├── kelly.py       # Kelly criterion
│   │   ├── ws.py          # WebSocket 实时价格
│   │   ├── observation.py # METAR 观测过滤
│   │   └── paper_trade.py # 纸面交易
│   ├── strategies/
│   │   ├── base.py        # 策略基类
│   │   ├── gopfan2.py     # 尾部 YES 策略
│   │   └── forecast_arb.py # 模型 vs 市场 mispricing
│   ├── backtest/
│   │   ├── engine.py      # 回测引擎
│   │   ├── real_data.py   # 真实市场数据
│   │   └── costs.py       # 费用模型
│   └── cli/               # CLI 命令
├── docs/                  # 研究文档
├── config.toml            # 配置
└── pyproject.toml         # 项目配置
```

## 配置

编辑 `config.toml`：

```toml
[clob]
api_key = ""         # 或设 CLOB_API_KEY 环境变量
api_secret = ""
api_passphrase = ""

[sizing]
max_single = 5.0     # 单笔最大 $5
max_daily = 50.0     # 日限额 $50
kelly_fraction = 0.25 # 1/4 Kelly
```

## 环境变量

| 变量 | 用途 |
|------|------|
| `POLY_PK` | Polymarket 私钥 |
| `CLOB_API_KEY` | CLOB API Key |
| `CLOB_SECRET` | CLOB Secret |
| `CLOB_PASS_PHRASE` | CLOB Passphrase |

## 开发

```bash
ruff check bots/
mypy bots/
```

## Disclaimer

This software is for educational and research purposes only. Trading involves significant financial risk. Past performance does not guarantee future results.
