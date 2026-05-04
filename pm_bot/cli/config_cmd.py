from __future__ import annotations

from rich.console import Console
from rich.table import Table

from pm_bot.models.config import DEFAULT_CITIES, STRATEGY_DEFAULTS, CACHE_TTL


def run_config() -> None:
    console = Console()

    console.print("\n[bold]PM-Bot Configuration[/]\n")

    table = Table(title="Strategy Defaults", show_lines=False)
    table.add_column("Strategy", style="cyan")
    table.add_column("Parameter", style="white")
    table.add_column("Value", style="green")

    for strat, params in STRATEGY_DEFAULTS.items():
        for k, v in params.items():
            table.add_row(strat, k, f"{v}")

    console.print(table)

    console.print(f"\n[bold]Default Cities:[/] {', '.join(DEFAULT_CITIES)}")
    console.print("[dim]Override with --cities NYC,HK or --all[/dim]")

    cache_table = Table(title="Cache TTL", show_lines=False)
    cache_table.add_column("Data", style="cyan")
    cache_table.add_column("TTL (seconds)", style="green")

    for name, ttl in CACHE_TTL.items():
        cache_table.add_row(name, str(ttl))

    console.print(cache_table)
    console.print("\n[dim]Set --edge <value> to override all strategy edge thresholds[/dim]")
    console.print("[dim]Set --debug for structured request logging[/dim]")
