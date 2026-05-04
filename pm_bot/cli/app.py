from __future__ import annotations

import asyncio
from typing import Optional

import typer

app = typer.Typer(
    name="pm-bot",
    help="Polymarket weather market strategy scanner",
    no_args_is_help=True,
)


@app.command()
def scan(
    strategy: str = typer.Option("all", "--strategy", "-s", help="Strategy: all, gopfan2, sum_arb, ladder"),
    cities: Optional[str] = typer.Option(None, "--cities", "-c", help="Comma-separated cities (e.g. NYC,HK,MIA)"),
    all_cities: bool = typer.Option(False, "--all", help="Scan all available cities"),
    edge: Optional[float] = typer.Option(None, "--edge", "-e", help="Override minimum edge threshold"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed reasoning"),
    closed: bool = typer.Option(False, "--closed", help="Include closed/settled markets"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
):
    """Scan markets and output strategy recommendations."""
    from pm_bot.cli.scan import run_scan
    asyncio.run(run_scan(
        strategy=strategy,
        cities_str=cities,
        all_cities=all_cities,
        edge_override=edge,
        verbose=verbose,
        include_closed=closed,
        debug=debug,
    ))


@app.command()
def markets(
    cities: Optional[str] = typer.Option(None, "--cities", "-c", help="Filter by cities"),
    all_cities: bool = typer.Option(False, "--all", help="Show all available cities"),
    closed: bool = typer.Option(False, "--closed", help="Include closed/settled markets"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
):
    """List current weather markets on Polymarket."""
    from pm_bot.cli.markets import run_markets
    asyncio.run(run_markets(cities_str=cities, all_cities=all_cities, include_closed=closed, debug=debug))


@app.command()
def watch(
    interval: int = typer.Option(60, "--interval", "-i", help="Refresh interval in seconds"),
    strategy: str = typer.Option("all", "--strategy", "-s", help="Strategy filter"),
    cities: Optional[str] = typer.Option(None, "--cities", "-c", help="Comma-separated cities"),
    all_cities: bool = typer.Option(False, "--all", help="Scan all available cities"),
    edge: Optional[float] = typer.Option(None, "--edge", "-e", help="Override edge threshold"),
    closed: bool = typer.Option(False, "--closed", help="Include closed/settled markets"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
):
    """TUI continuous monitoring mode."""
    from pm_bot.cli.watch import run_watch
    asyncio.run(run_watch(
        interval=interval,
        strategy=strategy,
        cities_str=cities,
        all_cities=all_cities,
        edge_override=edge,
        include_closed=closed,
        debug=debug,
    ))


@app.command()
def explain(
    market_id: str = typer.Argument(help="Market or event ID to explain"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
):
    """Show detailed strategy reasoning for a specific market."""
    from pm_bot.cli.explain import run_explain
    asyncio.run(run_explain(market_id=market_id, debug=debug))


@app.command()
def config():
    """Show current configuration."""
    from pm_bot.cli.config_cmd import run_config
    run_config()
