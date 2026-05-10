# Polymarket Bot 合集

> 一组自动化交易机器人，用于 [Polymarket](https://polymarket.com) 预测市场。

## 机器人列表

| Bot | 目录 | 目标 | 策略 |
|-----|------|------|------|
| **天气 Bot** | `bots/weather/` | 每日天气市场 | 模型 vs 市场定价偏差，尾部 YES 彩票 |
| **聪明钱包 Bot** | `bots/smart_wallet/` | 全平台跟单 | 跟随高胜率钱包 + 逆向策略 |

---

## 1. 天气 Bot (`bots/weather/`)

基于多源天气预报（Open-Meteo GEFS 31成员集合、NWS、METAR）的 Polymarket 每日天气市场交易系统。

```bash
# 扫描市场
pm-bot scan --cities "New York,London,Tokyo"

# 回测
pm-bot backtest --strategy gopfan2 --days 90 --bankroll 100 --live

# 实盘交易
pm-bot trade --confirm
```

详见: `bots/weather/README.md` (TODO)

---

## 2. 聪明钱包 Bot (`bots/smart_wallet/`)

基于 Polymarket 链上数据分析的跟单交易系统。识别高胜率钱包并跟随/逆向交易。

```bash
# 发现聪明钱包
python bots/smart_wallet/run.py discover

# 回测
python bots/smart_wallet/run.py backtest

# 实时监控
python bots/smart_wallet/run.py live

# 完整流水线
python bots/smart_wallet/run.py full-pipeline
```

详见: [docs/SMART_WALLET_STRATEGY.md](docs/SMART_WALLET_STRATEGY.md)

---

## 项目结构

```
pm/
├── bots/                            # Bot 目录
│   ├── weather/                     # 天气 Bot
│   │   ├── core/                    # 核心模块
│   │   ├── strategies/              # 策略
│   │   ├── backtest/                # 回测框架
│   │   ├── cli/                     # CLI 命令
│   │   └── run_snowball.py          # 独立运行脚本
│   └── smart_wallet/                # 聪明钱包 Bot
│       ├── api.py                   # API 客户端
│       ├── tracker.py               # 钱包发现
│       ├── strategy.py              # 策略
│       ├── backtest.py              # 回测
│       ├── monitor.py               # 实时监控
│       └── run.py                   # 独立运行脚本
├── shared/                          # 共享模块
│   └── polymarket.py                # 共享 API 客户端
├── docs/                            # 文档
│   ├── polymarket-trading-bot-plan.md
│   └── SMART_WALLET_STRATEGY.md
├── AGENTS.md                        # AI Agent 指南
├── README.md                        # 本文件
└── pyproject.toml                   # 项目配置
```

## 共享资源

- `shared/polymarket.py` — 共享的 Polymarket API 客户端
- `AGENTS.md` — AI Agent 开发指南
- `docs/` — 策略文档和研究计划

## 开发

```bash
# 安装依赖
uv sync

# Lint
ruff check bots/ shared/

# 类型检查
mypy bots/ shared/

# 测试
pytest tests/ -q
```

## License

MIT License. See [LICENSE](LICENSE) for details.

## Disclaimer

This software is for educational and research purposes only. Trading on prediction markets involves significant financial risk. Past backtest performance does not guarantee future results. The authors are not responsible for any financial losses incurred through use of this software.
