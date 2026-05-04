from __future__ import annotations

import asyncio
from typing import Optional

import typer

app = typer.Typer(
    name="pm-bot",
    help="Polymarket weather market strategy scanner",
    no_args_is_help=True,
)

daemon_app = typer.Typer(help="24/7 automated trading daemon", no_args_is_help=True)
app.add_typer(daemon_app, name="daemon")


@app.command()
def scan(
    strategy: str = typer.Option("all", "--strategy", "-s", help="Strategy: all, gopfan2, sum_arb, ladder, narrow_no, airport_arb"),
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
    interval: int = typer.Option(60, "--interval", "-i", help="Refresh interval in seconds (polling fallback)"),
    strategy: str = typer.Option("all", "--strategy", "-s", help="Strategy filter"),
    cities: Optional[str] = typer.Option(None, "--cities", "-c", help="Comma-separated cities"),
    all_cities: bool = typer.Option(False, "--all", help="Scan all available cities"),
    edge: Optional[float] = typer.Option(None, "--edge", "-e", help="Override edge threshold"),
    closed: bool = typer.Option(False, "--closed", help="Include closed/settled markets"),
    no_ws: bool = typer.Option(False, "--no-ws", help="Disable WebSocket, use polling only"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
):
    """TUI continuous monitoring mode with WebSocket real-time prices."""
    from pm_bot.cli.watch import run_watch
    asyncio.run(run_watch(
        interval=interval,
        strategy=strategy,
        cities_str=cities,
        all_cities=all_cities,
        edge_override=edge,
        include_closed=closed,
        use_ws=not no_ws,
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
def trade(
    strategy: str = typer.Option("all", "--strategy", "-s", help="Strategy filter"),
    cities: Optional[str] = typer.Option(None, "--cities", "-c", help="Comma-separated cities"),
    all_cities: bool = typer.Option(False, "--all", help="Scan all available cities"),
    edge: Optional[float] = typer.Option(None, "--edge", "-e", help="Override edge threshold"),
    closed: bool = typer.Option(False, "--closed", help="Include closed/settled markets"),
    confirm: bool = typer.Option(False, "--confirm", help="Confirm and execute trades (requires CLOB credentials)"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
):
    """Scan markets and optionally execute trades with confirmation."""
    from pm_bot.cli.trade import run_trade
    asyncio.run(run_trade(
        strategy=strategy,
        cities_str=cities,
        all_cities=all_cities,
        edge_override=edge,
        include_closed=closed,
        confirm=confirm,
        debug=debug,
    ))


@app.command()
def orders(
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
):
    """Show current open orders and trade status."""
    from pm_bot.cli.orders import run_orders
    asyncio.run(run_orders(debug=debug))


@app.command()
def config(
    init: bool = typer.Option(False, "--init", help="Generate template config.toml"),
):
    """Show current configuration or generate template."""
    from pm_bot.cli.config_cmd import run_config
    run_config(init=init)


@daemon_app.command("start")
def daemon_start_cmd(
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
):
    """Start the 24/7 automated trading daemon."""
    from pm_bot.cli.daemon import daemon_start
    asyncio.run(daemon_start(debug=debug))


@daemon_app.command("stop")
def daemon_stop_cmd(
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
):
    """Stop the running daemon gracefully."""
    from pm_bot.cli.daemon import daemon_stop
    asyncio.run(daemon_stop(debug=debug))


@daemon_app.command("status")
def daemon_status_cmd(
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
):
    """Show daemon status, P&L, and open orders."""
    from pm_bot.cli.daemon import daemon_status
    asyncio.run(daemon_status(debug=debug))
