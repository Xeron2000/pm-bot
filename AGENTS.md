# Polymarket Bot 合集 — AI Agent 指南

## 项目概述

Polymarket 预测市场自动交易机器人合集。每个 Bot 独立运作，共享基础设施。

## 目录结构

```
pm/
├── bots/                            # Bot 目录 (每个 Bot 独立)
│   ├── weather/                     # 天气 Bot
│   └── smart_wallet/                # 聪明钱包 Bot
├── shared/                          # 共享模块
│   └── polymarket.py                # 共享 API 客户端
├── docs/                            # 文档
└── AGENTS.md                        # 本文件
```

## Bot 列表

### 天气 Bot (`bots/weather/`)
- **目标**: Polymarket 每日天气市场（NYC, London, Tokyo）
- **策略**: `gopfan2` — 尾部YES彩票
- **入口**: `pm-bot scan|trade|backtest|daemon`
- **核心**: `bots/weather/core/`, `bots/weather/strategies/`

### 聪明钱包 Bot (`bots/smart_wallet/`)
- **目标**: 全平台跟单交易
- **策略**: 跟随高胜率钱包 (Copy) + 逆向高价入场 (Inverse)
- **入口**: `python bots/smart_wallet/run.py discover|backtest|live`
- **核心**: `bots/smart_wallet/api.py`, `bots/smart_wallet/strategy.py`

## 共享模块 (`shared/`)

| 模块 | 用途 |
|------|------|
| `shared/polymarket.py` | 共享 Polymarket API 客户端 |

## 文档 (`docs/`)

| 文件 | 用途 |
|------|------|
| `docs/SMART_WALLET_STRATEGY.md` | 聪明钱包策略完整文档 |
| `docs/polymarket-trading-bot-plan.md` | 早期研究计划 |

## 开发指南

### 新增 Bot
1. 在 `bots/` 下创建新目录（如 `bots/my_bot/`）
2. 创建 `__init__.py`, `run.py` (入口), 核心模块
3. 复用 `shared/polymarket.py` 的 API 客户端
4. 更新 README.md 和本文档

### 代码风格
- Python 3.12+
- 使用 `uv` 管理依赖
- `ruff` 格式化 + `mypy` 类型检查
- 异步优先 (`asyncio`, `httpx`)

### API 端点

| 端点 | 用途 | 认证 |
|------|------|------|
| `https://data-api.polymarket.com/trades` | 交易历史 | 无需 |
| `https://gamma-api.polymarket.com/markets` | 市场列表 | 无需 |
| `https://clob.polymarket.com/*` | 交易执行 | 需要 API Key |

### 测试
```bash
pytest tests/ -q
```

---

<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

## Subagents

- ALWAYS wait for all subagents to complete before yielding.
- Spawn subagents automatically when:
  - Parallelizable work (e.g., install + verify, npm test + typecheck, multiple tasks from plan)
  - Long-running or blocking tasks where a worker can run independently.
  - Isolation for risky changes or checks

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->
