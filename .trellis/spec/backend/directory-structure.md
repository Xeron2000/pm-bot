# Directory Structure

> How backend code is organized in this project.

---

## Overview

Single-package Python CLI app using Typer + Rich. No frontend layer (TUI only).

---

## Directory Layout

```
pm_bot/
  __init__.py
  __main__.py            # python -m pm_bot entry point
  core/
    __init__.py
    polymarket.py        # Gamma/CLOB API client, event parsing
    weather.py           # Open-Meteo forecast client
    parser.py            # Temperature bucket title parser (regex)
  strategies/
    __init__.py          # Re-exports all strategy classes + ALL_STRATEGIES
    base.py              # Strategy protocol + all 3 strategy implementations
  cli/
    __init__.py
    app.py               # Typer app definition, command registration
    scan.py              # scan command
    watch.py             # watch TUI command
    markets.py           # markets command
    explain.py           # explain command
    config_cmd.py        # config command
    display.py           # Rich table/panel rendering
  models/
    __init__.py          # Re-exports all model classes + config
    market.py            # WeatherEvent, TemperatureBucket, ForecastResult, Recommendation
    config.py            # CITY_COORDS, CITY_ALIASES, STRATEGY_DEFAULTS, CACHE_TTL
```

---

## Module Organization

- `core/` — I/O boundary: API clients, parsers, caching. All external calls live here.
- `strategies/` — Pure computation: takes models, returns recommendations. No I/O.
- `cli/` — Presentation layer: Typer commands, Rich output. Orchestrates core + strategies.
- `models/` — Data definitions: dataclasses, config constants. No logic.

### Dependency direction

```
cli → strategies → models ← core
  ↘     core    ↗
```

- `models` is the shared leaf (no imports from other app modules)
- `core` imports from `models` only
- `strategies` imports from `models` only
- `cli` imports from all other modules

---

## Naming Conventions

- Package: `pm_bot` (snake_case)
- CLI entry: `pm-bot` (kebab-case) via `pyproject.toml [project.scripts]`
- Files: snake_case (`config_cmd.py` to avoid `config` shadowing stdlib)
- Strategy classes: PascalCase (`Gopfan2Strategy`, `SumArbStrategy`, `LadderStrategy`)
- Config keys: snake_case (`yes_max`, `no_min`, `gap_min`, `edge_min`)

---

## Examples

Well-organized module: `pm_bot/core/polymarket.py`
- Single responsibility: Gamma API client + event parsing
- All I/O in one place, cached via module-level TTLCache
- Returns typed dataclasses from `models`
