# Polymarket Weather Trading Bot

> 自动化 Polymarket 每日天气市场交易机器人。基于 EMOS 校准的多模型集合预报，实现模型 vs 市场定价偏差策略。

## 核心特性

- **EMOS 校准** — 修复集合预报欠散问题，提高概率估计准确性
- **多模型集成** — GFS + ECMWF IFS + ICON + GEM 四模型加权
- **智能城市选择** — 基于竞争程度和流动性自动选择最优市场
- **Barbell 策略** — ColdMath 风格：尾部小仓位 + 中央高信心仓位
- **风险管理** — 三级熔断器、仓位限额、连续亏损暂停

## 快速开始

```bash
# 安装
uv sync

# 查看所有命令
pm-bot-v2 --help

# 扫描市场机会
pm-bot-v2 scan --cities "Chicago,Miami,Buenos Aires"

# 训练 EMOS 校准器
pm-bot-v2 train --all --days 90

# 纸面交易
pm-bot-v2 paper --bankroll 100 --min-edge 0.08

# 回测
pm-bot-v2 backtest --strategy barbell --days 30 --real

# 查看状态
pm-bot-v2 status
```

## 策略列表

| 策略 | 描述 | 适用场景 |
|------|------|----------|
| `gopfan2` | 尾部 YES 彩票（价格 < $0.15） | 简单快速 |
| `forecast_arb` | 模型 vs 市场 mispricing | 中等复杂度 |
| `emos_gopfan2` | EMOS 增强的 gopfan2 | 更准确的概率 |
| `emos_forecast_arb` | EMOS 增强的 forecast_arb | 最佳校准 |
| `barbell` | 尾部 + 中央仓位组合 | ColdMath 风格 |
| `adaptive_barbell` | 自适应 barbell | 动态调整 |

## 项目结构

```
pm/
├── bots/weather/
│   ├── core/              # 核心模块
│   │   ├── weather.py     # Open-Meteo 集合预报
│   │   ├── emos.py        # EMOS 校准
│   │   ├── ensemble.py    # 多模型集成
│   │   ├── city_selector.py # 城市选择
│   │   ├── clob.py        # Polymarket CLOB 交易
│   │   ├── risk.py        # 风险管理
│   │   ├── kelly.py       # Kelly criterion
│   │   └── ws.py          # WebSocket 实时价格
│   ├── strategies/
│   │   ├── base.py        # 策略基类 + gopfan2
│   │   ├── forecast_arb.py # Forecast arbitrage
│   │   ├── emos_strategies.py # EMOS 增强策略
│   │   └── barbell.py     # Barbell 策略
│   ├── backtest/
│   │   ├── engine.py      # 回测引擎
│   │   ├── real_data.py   # 真实市场数据
│   │   └── costs.py       # 费用模型
│   ├── scripts/
│   │   ├── scan_markets.py # 市场扫描
│   │   ├── train_emos.py  # EMOS 训练
│   │   └── trade_bot.py   # 交易机器人
│   └── cli/
│       ├── app.py         # 原始 CLI
│       └── app_v2.py      # 新 CLI（推荐）
├── config.template.toml   # 配置模板
├── data/emos/             # EMOS 校准器存储
└── docs/                  # 研究文档
```

## 配置

复制配置模板：

```bash
cp config.template.toml config.toml
```

编辑 `config.toml`：

```toml
[mode]
mode = "paper"  # paper 或 live

[sizing]
bankroll = 100.0
kelly_fraction = 0.25

[daemon]
cities = ["Chicago", "Miami", "Buenos Aires"]
scan_interval = 300  # 5 分钟

[clob]
clob_api_key = ""
clob_secret = ""
clob_pass_phrase = ""
poly_pk = ""
```

## 环境变量

| 变量 | 用途 |
|------|------|
| `POLY_PK` | Polymarket 私钥 |
| `CLOB_API_KEY` | CLOB API Key |
| `CLOB_SECRET` | CLOB Secret |
| `CLOB_PASS_PHRASE` | CLOB Passphrase |

## 策略详解

### Barbell 策略（推荐）

ColdMath 风格的 barbell 策略：

**尾部仓位（80%）：**
- 价格 < $0.15（gopfan2 规则）
- 模型概率 > 18%
- 最大 $2/仓位，Quarter Kelly

**中央仓位（20%）：**
- 需要 20%+ edge（高信心）
- 最大 $5/仓位，10% Kelly
- 支持 YES 和 NO 方向

### EMOS 校准

EMOS（Ensemble Model Output Statistics）修复集合预报欠散：

```
Raw ensemble: N(μ_ensemble, σ²_ensemble) — often underdispersive
EMOS calibrated: N(a + b·μ_ensemble, c + d·σ²_ensemble)
```

训练命令：

```bash
# 训练单个城市
pm-bot-v2 train --city "Chicago" --days 90

# 训练所有城市
pm-bot-v2 train --all --days 60
```

## 回测

```bash
# 合成数据回测
pm-bot-v2 backtest --strategy gopfan2 --days 30

# 真实数据回测
pm-bot-v2 backtest --strategy barbell --days 30 --real --cities Chicago,Miami

# EMOS 增强回测
pm-bot-v2 backtest --strategy emos_gopfan2 --emos --days 30
```

## 参考资源

- [polymarket-tmax-lab](https://github.com/YoungseokOh/polymarket-tmax-lab) — EMOS 实现
- [gopfan2 策略](https://polymarketweather.com/blog/gopfan2-polymarket) — $343K+ 利润
- [ColdMath 策略](https://polymarketweather.com/blog/coldmath-polymarket) — $120K+ 利润
- [Windfall](http://windfall.polsia.app/) — Edge 检测工具
- [Degen Doppler](https://degendoppler.com/) — 14 模型集成

## 开发

```bash
# 代码检查
ruff check bots/
mypy bots/

# 运行测试
pytest tests/ -q
```

## Disclaimer

This software is for educational and research purposes only. Trading involves significant financial risk. Past performance does not guarantee future results.
