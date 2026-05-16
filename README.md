# Polymarket Weather Trading Bot

> 自动化 Polymarket 每日天气市场交易机器人。基于 EMOS 校准的多模型集合预报，实现模型 vs 市场定价偏差策略。

## 核心特性

- **EMOS 校准** — 修复集合预报欠散问题，提高概率估计准确性
- **多模型集成** — GFS + ECMWF IFS + ICON + GEM 四模型加权
- **智能城市选择** — 基于竞争程度和流动性自动选择最优市场
- **三策略组合** — Ladder + Tail + Gopfan2 互补策略
- **风险管理** — 熔断器、仓位限额、连续亏损暂停、Brier 分数监控

## 快速开始

```bash
# 安装
uv sync

# 查看所有命令
pm-bot-v2 --help

# 扫描市场机会
pm-bot-v2 scan --cities "Chicago,Miami,Buenos Aires"

# 训练 EMOS 校准器
pm-bot-v2 train --all --days 45

# 纸面交易
pm-bot-v2 paper --bankroll 100 --min-edge 0.08

# 查看状态
pm-bot-v2 status
```

## 策略架构

### 三策略组合（推荐）

| 策略 | 权重 | 买入价格 | 胜率 | 核心逻辑 |
|------|------|----------|------|----------|
| **Ladder** | 40% | < 20¢ | 16-20% | 相邻温度桶覆盖，neobrother 模式 |
| **Tail** | 30% | < 15¢ | 18-23% | 尾部低估桶，Hans323 模式 |
| **Gopfan2** | 30% | < 15¢ | 23-30% | 简单价格规则，模型支持 |

**为什么都买便宜桶？**
- 价格 < 20¢ 时流动性充足（深度 $500-2000）
- 赢了赚 $0.80-0.95，输了亏 $0.05-0.15
- 盈亏比 8-10:1，只需 10-12% 胜率即可盈利
- 避免价格冲击（大额买入不会大幅抬价）

### 策略详解

**Ladder Strategy（梯子策略）**
```
买入条件：
- 模型预测温度 ±3°C 范围内的相邻桶
- 价格 < 20¢
- Edge > 3%

仓位计算：
- 每桶 Kelly 15% × 距离衰减系数
- 最多 4 个相邻桶
- 总仓位 < 40%
```

**Tail Strategy（尾部策略）**
```
买入条件：
- 价格 < 12¢（尾部桶）
- 模型概率 > 8%（真实可能性）
- Edge > 5%

仓位计算：
- Kelly 10% × 边际强度
- 最多 10% 单桶
- 最多 30% 总仓位
```

**Gopfan2 Strategy（简单规则）**
```
买入条件：
- YES: 价格 < 15¢ 且模型概率 > 1.5× 价格
- NO: 价格 > 45¢ 且模型反对概率 > 1.3× NO 价格

仓位计算：
- Kelly 20%
- 最多 5% 单桶
- $1-3/笔交易
```

## 项目结构

```
pm/
├── bots/weather/
│   ├── core/              # 核心模块
│   │   ├── weather.py     # 多模型集成预报 + EMOS 校准
│   │   ├── emos.py        # EMOS 训练器
│   │   ├── observation.py # METAR 实时观测
│   │   ├── city_selector.py # 城市选择 + 流动性分级
│   │   ├── clob.py        # Polymarket CLOB 交易
│   │   ├── risk.py        # 风险管理
│   │   ├── kelly.py       # Kelly criterion
│   │   └── ws.py          # WebSocket 实时价格
│   ├── strategies/
│   │   ├── base.py        # 策略基类
│   │   └── emos_edge.py   # EMOS Edge 生产策略（含 Ladder/Tail/Gopfan2）
│   ├── backtest/
│   │   ├── engine.py      # 回测引擎
│   │   ├── weather_strategies.py # 回测用策略实现
│   │   └── costs.py       # 费用模型
│   ├── scripts/
│   │   ├── scan_markets.py # 市场扫描
│   │   └── train_emos.py  # EMOS 训练
│   └── cli/
│       └── app_v2.py      # CLI 入口
├── data/
│   └── emos_coeffs/       # 14 城市 EMOS 系数
├── paper_trade.py         # 纸面交易机器人
├── run_weather_backtest.py # 综合回测脚本
└── config.toml            # 配置文件
```

## EMOS 校准

EMOS（Ensemble Model Output Statistics）修复集合预报欠散：

```
Raw ensemble: N(μ_ensemble, σ²_ensemble) — often underdispersive
EMOS calibrated: N(a + b·μ_ensemble, c + d·σ²_ensemble)
```

### 已训练城市（45 天窗口）

| 城市 | a (偏置) | b (斜率) | c (基础方差) | d (扩散系数) |
|------|----------|----------|--------------|--------------|
| New York | +0.012 | 1.064 | 0.349 | 0.108 |
| Miami | +0.004 | 0.979 | 0.087 | 0.235 |
| Dallas | -1.190 | 1.028 | 0.167 | 0.649 |
| Chicago | +0.332 | 0.990 | 0.070 | 0.490 |
| London | -0.410 | 1.033 | 0.171 | 0.035 |
| Paris | -0.866 | 1.054 | 0.257 | 0.201 |
| Tokyo | -0.243 | 1.010 | 0.322 | 0.538 |
| Seoul | -1.015 | 1.025 | 0.132 | 0.442 |
| Shanghai | +0.006 | 0.980 | 0.465 | 0.221 |
| Hong Kong | +0.002 | 0.978 | 0.040 | 0.630 |

训练命令：

```bash
# 训练单个城市
pm-bot-v2 train --city "Chicago" --days 45

# 训练所有城市
pm-bot-v2 train --all --days 45
```

## 回测结果（合成数据，90 天，$100 起始）

| 策略 | 收益 | 交易数 | 胜率 | 盈亏比 | Sharpe |
|------|------|--------|------|--------|--------|
| Ladder | +1530% | 693 | 16% | 10.6:1 | 5.69 |
| Gopfan2 | +982% | 377 | 23% | 8.7:1 | 9.48 |
| Tail | +820% | 266 | 18% | 8.1:1 | 6.49 |
| **Combined** | **+4013%** | 1346 | 22% | 9.1:1 | 14.65 |

**⚠️ 警告：合成数据回测严重高估收益**
- 真实市场收益 = 回测收益 × 0.1-0.3
- 原因：合成数据偏差、竞争差距、执行假设、流动性限制
- 预期真实月收益：20-40%（保守）到 50-80%（乐观）

## 纸面交易

```bash
# 运行一次
uv run python3 paper_trade.py

# 持续运行（每小时）
uv run python3 paper_trade.py --loop

# 查看状态
uv run python3 paper_trade.py --status
```

### 服务器部署（Cron）

```bash
# 每小时运行
0 * * * * cd /root/pm-bot && /root/.local/bin/uv run python3 paper_trade.py >> /root/.pm-bot/paper-trade.log 2>&1
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
cities = ["New York", "London", "Tokyo", "Shanghai", "Seoul"]
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
| `PAPER_BANKROLL` | 纸面交易起始资金（默认 $100） |

## 交易规则

### 每日流程

```
00:05 UTC  → 醒来，获取 GFS + ECMWF 更新
00:10 UTC  → 扫描 12 城市天气市场
00:15 UTC  → 计算边际，执行交易
00:30 UTC  → 回去睡觉
次日       → 查看结算结果
```

**每天只需 15-30 分钟，无需日内监控。**

### 风险管理

- **仓位限制**：单笔 ≤ 5% 资金，总仓位 ≤ 40%
- **止损规则**：日亏 > 20% 停止交易，周亏 > 30% 休息 3 天
- **每周提取**：利润的 30-50% 提现
- **每月重训**：EMOS 系数需要每月重新训练

### 流动性建议

| 资金规模 | 每笔交易 | 月收益预期 | 说明 |
|----------|----------|------------|------|
| < $200 | $2 固定 | 30-50% | 学习阶段 |
| $200-500 | $5 固定 | 20-40% | 正常复利 |
| $500-1000 | 2% 风险 | 15-30% | 流动性开始限制 |
| > $1000 | 1% 风险 | 10-20% | 需要分散市场 |

## 参考资源

- [polymarket-tmax-lab](https://github.com/YoungseokOh/polymarket-tmax-lab) — EMOS 实现
- [Polymarket Weather](https://polymarketweather.com) — 85-90% 命中率的商业 bot
- [Hans323](https://polymarket.com/profile/Hans323) — $1.1M 利润，51% 胜率
- [neobrother](https://polymarket.com/profile/neobrother) — $20K+ 利润，梯子策略
- [securebet](https://polymarket.com/profile/securebet) — $7→$640，3000+ 微预测

## 开发

```bash
# 代码检查
ruff check bots/
mypy bots/

# 运行测试
pytest tests/ -q

# 语法验证
python3 -c "import ast; ast.parse(open('paper_trade.py').read())"
```

## Disclaimer

This software is for educational and research purposes only. Trading involves significant financial risk. Past performance does not guarantee future results. The backtest results shown are from synthetic data and will significantly overestimate real-world returns.
