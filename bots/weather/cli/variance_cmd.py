"""CLI command: pm-bot variance — city variance filtering.

Shows city variance scores, tier classifications, and tradeability status.
Can also populate variance data from historical backtest data.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog
from rich.console import Console
from rich.table import Table

from pm_bot.core.city_variance import (
    CITY_TIER_PRIORS,
    DEFAULT_MAX_MAE,
    DEFAULT_MAX_STD,
    CityVarianceDB,
)
from pm_bot.models.config import CITY_COORDS, DEFAULT_CITIES, resolve_city_alias

console = Console()
log = structlog.get_logger()


async def run_variance(
    populate: bool = False,
    days: int = 90,
    max_mae: float = DEFAULT_MAX_MAE,
    max_std: float = DEFAULT_MAX_STD,
    show_all: bool = False,
    debug: bool = False,
) -> None:
    """Run variance command."""
    if debug:
        import logging

        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG))

    db = CityVarianceDB()

    if populate:
        await _populate_variance(db, days)

    _show_variance_table(db, max_mae, max_std, show_all)


async def _populate_variance(db: CityVarianceDB, days: int) -> None:
    """Populate variance data from historical forecasts vs observations."""
    from pm_bot.backtest.data import HistoricalDataFetcher

    console.print(f"[bold]Populating variance data from last {days} days...[/bold]")

    fetcher = HistoricalDataFetcher()
    async with httpx.AsyncClient(timeout=30.0) as client:
        from datetime import datetime, timedelta, timezone

        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days)

        total_records = 0
        for city in DEFAULT_CITIES:
            canonical = resolve_city_alias(city)
            if canonical not in CITY_COORDS:
                continue

            city_count = 0
            current = start_date
            while current <= end_date:
                date_str = current.strftime("%Y-%m-%d")
                forecast = await fetcher.fetch_historical_forecasts(client, canonical, date_str)
                obs = await fetcher.fetch_historical_observations(client, canonical, date_str)

                if forecast is not None and obs is not None:
                    db.record(canonical, forecast.temp_high_c, obs)
                    city_count += 1

                current += timedelta(days=1)

            if city_count > 0:
                console.print(f"  {canonical}: {city_count} records")
                total_records += city_count

    fetcher.close()
    console.print(f"[green]Populated {total_records} total records.[/green]\n")


def _show_variance_table(
    db: CityVarianceDB,
    max_mae: float,
    max_std: float,
    show_all: bool,
) -> None:
    """Display variance scores in a Rich table."""
    table = Table(title="City Variance Filter")
    table.add_column("City", style="cyan")
    table.add_column("Tier", style="bold")
    table.add_column("MAE (°C)", justify="right")
    table.add_column("Std (°C)", justify="right")
    table.add_column("Bias (°C)", justify="right")
    table.add_column("Samples", justify="right")
    table.add_column("Tradeable", justify="center")
    table.add_column("Prior", style="dim")

    tier_colors = {
        "low": "green",
        "medium": "yellow",
        "high": "red",
        "unknown": "dim",
    }

    cities = DEFAULT_CITIES if show_all else db.get_tradeable_cities(max_mae, max_std)

    # Show all cities if show_all, otherwise show tradeable + blocked
    display_cities = DEFAULT_CITIES if show_all else DEFAULT_CITIES

    for city_name in display_cities:
        city = resolve_city_alias(city_name)
        entry = db.get_entry(city)
        tier = db.get_tier(city)
        prior = CITY_TIER_PRIORS.get(city, "unknown")
        tradeable = db.is_tradeable(city, max_mae, max_std)

        if entry and entry.sample_count > 0:
            mae_str = f"{entry.mae:.2f}"
            std_str = f"{entry.std:.2f}"
            bias_str = f"{entry.mean_error:+.2f}"
            samples_str = str(entry.sample_count)
        else:
            mae_str = "[dim]—[/dim]"
            std_str = "[dim]—[/dim]"
            bias_str = "[dim]—[/dim]"
            samples_str = "[dim]0[/dim]"

        tier_color = tier_colors.get(tier, "white")
        tradeable_str = "[green]✓[/green]" if tradeable else "[red]✗[/red]"

        # Skip cities with no data and unknown prior unless show_all
        if not show_all and not tradeable:
            continue

        table.add_row(
            city,
            f"[{tier_color}]{tier}[/{tier_color}]",
            mae_str,
            std_str,
            bias_str,
            samples_str,
            tradeable_str,
            prior,
        )

    console.print(table)
    console.print()
    console.print(f"[dim]Thresholds: MAE ≤ {max_mae}°C, Std ≤ {max_std}°C[/dim]")
    console.print("[dim]Use --all to show all cities, --populate to load historical data[/dim]")
