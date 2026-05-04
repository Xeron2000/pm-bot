from __future__ import annotations

import asyncio

import httpx
import structlog
from rich.console import Console

from pm_bot.core.polymarket import fetch_weather_events
from pm_bot.core.weather import fetch_forecast
from pm_bot.strategies.base import ALL_STRATEGIES, Strategy
from pm_bot.models.config import DEFAULT_CITIES, STRATEGY_DEFAULTS, resolve_city_alias
from pm_bot.cli.display import render_recommendations

console = Console()


async def run_watch(
    interval: int = 60,
    strategy: str = "all",
    cities_str: str | None = None,
    all_cities: bool = False,
    edge_override: float | None = None,
    include_closed: bool = False,
    debug: bool = False,
) -> None:
    _setup_logging(debug)

    cities = _resolve_cities(cities_str)
    strategies = _resolve_strategies(strategy)

    console.print(f"[bold]PM-Bot Watch[/] — refreshing every {interval}s. Ctrl+C to stop.")

    try:
        while True:
            async with httpx.AsyncClient(timeout=30.0) as client:
                events = await fetch_weather_events(client, include_closed=include_closed)
                if not all_cities:
                    events = [e for e in events if e.city in cities]

                forecasts = {}
                for ev in events:
                    fc = await fetch_forecast(client, ev.city, ev.date)
                    if fc:
                        forecasts[ev.city] = fc

                all_recs = []
                for ev in events:
                    for strat_name, strat in strategies:
                        kwargs: dict = {}
                        for k, v in STRATEGY_DEFAULTS.get(strat_name, {}).items():
                            kwargs[k] = edge_override if k in ("edge_min",) and edge_override else v
                        if strat_name == "ladder" and ev.city in forecasts:
                            kwargs["forecast"] = forecasts[ev.city]
                        recs = strat.run(ev, **kwargs)
                        if edge_override is not None:
                            recs = [r for r in recs if r.edge >= edge_override]
                        all_recs.extend(recs)

            console.clear()
            render_recommendations(all_recs)
            console.print(f"\n[dim]Next refresh in {interval}s...[/dim]")
            await asyncio.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n[yellow]Watch stopped.[/yellow]")


def _resolve_cities(cities_str: str | None) -> set[str]:
    if cities_str:
        return {resolve_city_alias(c.strip()) for c in cities_str.split(",")}
    return {resolve_city_alias(c) for c in DEFAULT_CITIES}


def _resolve_strategies(name: str) -> list[tuple[str, Strategy]]:
    if name == "all":
        return list(ALL_STRATEGIES.items())
    if name in ALL_STRATEGIES:
        return [(name, ALL_STRATEGIES[name])]
    return list(ALL_STRATEGIES.items())


def _setup_logging(debug: bool) -> None:
    import logging
    if debug:
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG))
    else:
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
