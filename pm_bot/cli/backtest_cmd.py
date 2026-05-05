from __future__ import annotations

from typing import Optional

import structlog
import typer
from rich.console import Console

from pm_bot.backtest.engine import BacktestEngine
from pm_bot.backtest.report import export_csv, render_comparison_table, render_table
from pm_bot.backtest.costs import CostModel
from pm_bot.strategies.base import get_all_strategies

console = Console()
log = structlog.get_logger()

backtest_app = typer.Typer(help="Backtesting framework", no_args_is_help=True)


@backtest_app.command("run")
def backtest_run(
    strategy: Optional[str] = typer.Option(None, "--strategy", "-s", help="Strategy name (omit for --all)"),
    all_strats: bool = typer.Option(False, "--all", help="Run all strategies"),
    compare: bool = typer.Option(False, "--compare", help="Show side-by-side comparison"),
    bankroll: float = typer.Option(100.0, "--bankroll", "-b", help="Starting bankroll in USD"),
    days: int = typer.Option(90, "--days", "-d", help="Number of days to backtest"),
    cities: Optional[str] = typer.Option("NYC", "--cities", "-c", help="Comma-separated cities"),
    csv_path: Optional[str] = typer.Option(None, "--csv", help="Export results to CSV file"),
    real: bool = typer.Option(False, "--real", help="Use real Polymarket historical prices and resolved outcomes"),
    stop_loss: float = typer.Option(0.0, "--stop-loss", help="Stop-loss as fraction of position (e.g. 0.5 = 50% stop-loss)"),
    kelly: float = typer.Option(0.25, "--kelly", help="Kelly fraction (0.25=quarter, 0.5=half, 1.0=full)"),
    max_pos: float = typer.Option(0.10, "--max-pos", help="Max single position as fraction of bankroll"),
    no_compound: bool = typer.Option(False, "--no-compound", help="Disable compounding (fixed bankroll)"),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
):
    """Run backtest against historical data."""
    import asyncio
    asyncio.run(_run_backtest(
        strategy=strategy,
        all_strats=all_strats,
        compare=compare,
        bankroll=bankroll,
        days=days,
        cities_str=cities,
        csv_path=csv_path,
        real=real,
        stop_loss=stop_loss,
        kelly=kelly,
        max_pos=max_pos,
        no_compound=no_compound,
        debug=debug,
    ))


async def _run_backtest(
    strategy: str | None,
    all_strats: bool,
    compare: bool,
    bankroll: float,
    days: int,
    cities_str: str | None,
    csv_path: str | None,
    real: bool,
    stop_loss: float,
    kelly: float,
    max_pos: float,
    no_compound: bool,
    debug: bool,
) -> None:
    _setup_logging(debug)

    all_strategies = get_all_strategies()

    if strategy and strategy in all_strategies:
        strats = [all_strategies[strategy]]
    elif all_strats or compare or strategy is None:
        strats = list(all_strategies.values())
    else:
        console.print(f"[red]Unknown strategy: {strategy}. Available: {', '.join(all_strategies)}[/red]")
        return

    city_list = [c.strip() for c in cities_str.split(",")] if cities_str else ["NYC"]

    mode_label = "real market data" if real else "synthetic prices"
    console.print(f"[bold]Running backtest ({mode_label}): {len(strats)} strategies, {days} days, ${bankroll:.0f} bankroll[/bold]")

    engine = BacktestEngine(
        strategies=strats,
        bankroll=bankroll,
        days=days,
        costs=CostModel(),
        cities=city_list,
        stop_loss_pct=stop_loss,
        kelly_fraction_val=kelly,
        max_single_pct=max_pos,
        compound=not no_compound,
    )

    if real:
        results = await engine.run_real()
    else:
        results = await engine.run()

    if not results:
        console.print("[yellow]No results produced.[/yellow]")
        return

    if compare:
        table = render_comparison_table(results)
    else:
        table = render_table(results)
    console.print(table)

    if csv_path:
        export_csv(results, csv_path)
        console.print(f"[green]CSV exported to {csv_path}[/green]")


def _setup_logging(debug: bool) -> None:
    import logging
    if debug:
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG))
    else:
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
