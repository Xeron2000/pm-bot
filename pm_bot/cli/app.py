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
    strategy: str = typer.Option(
        "all",
        "--strategy",
        "-s",
        help="Strategy: all, gopfan2, resolution_div, neg_risk_sum, truncation_edge, ensemble_spread, neg_risk_field_fade",
    ),
    cities: Optional[str] = typer.Option(None, "--cities", "-c", help="Comma-separated cities (e.g. NYC,HK,MIA)"),
    all_cities: bool = typer.Option(False, "--all", help="Scan all available cities"),
    edge: Optional[float] = typer.Option(None, "--edge", "-e", help="Override minimum edge threshold"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed reasoning"),
    closed: bool = typer.Option(False, "--closed", help="Include closed/settled markets"),
    observed: bool = typer.Option(False, "--observed", help="Filter with METAR observed temperatures (5PM+ local)"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
):
    """Scan markets and output strategy recommendations."""
    from pm_bot.cli.scan import run_scan

    asyncio.run(
        run_scan(
            strategy=strategy,
            cities_str=cities,
            all_cities=all_cities,
            edge_override=edge,
            verbose=verbose,
            include_closed=closed,
            observed=observed,
            debug=debug,
        )
    )


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
    observed: bool = typer.Option(False, "--observed", help="Filter with METAR observed temperatures (5PM+ local)"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
):
    """TUI continuous monitoring mode with WebSocket real-time prices."""
    from pm_bot.cli.watch import run_watch

    asyncio.run(
        run_watch(
            interval=interval,
            strategy=strategy,
            cities_str=cities,
            all_cities=all_cities,
            edge_override=edge,
            include_closed=closed,
            use_ws=not no_ws,
            observed=observed,
            debug=debug,
        )
    )


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
    observed: bool = typer.Option(False, "--observed", help="Filter with METAR observed temperatures (5PM+ local)"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
):
    """Scan markets and optionally execute trades with confirmation."""
    from pm_bot.cli.trade import run_trade

    asyncio.run(
        run_trade(
            strategy=strategy,
            cities_str=cities,
            all_cities=all_cities,
            edge_override=edge,
            include_closed=closed,
            confirm=confirm,
            observed=observed,
            debug=debug,
        )
    )


@app.command()
def settle(
    all_positions: bool = typer.Option(False, "--all", help="Redeem all redeemable positions"),
    condition_ids: Optional[str] = typer.Option(None, "--ids", help="Comma-separated condition IDs to redeem"),
    list_only: bool = typer.Option(False, "--list", help="List redeemable positions without redeeming"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
):
    """Redeem winning positions from resolved markets (V2 auto-settle)."""
    from pm_bot.cli.settle import run_settle

    run_settle(all_positions=all_positions, condition_ids_str=condition_ids, list_only=list_only, debug=debug)


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
    dry_run: bool = typer.Option(False, "--dry-run", help="Dry-run mode: log signals without placing orders"),
    strategies: Optional[str] = typer.Option(
        None, "--strategies", "-s", help="Comma-separated strategy names (default: all)"
    ),
    kelly: Optional[float] = typer.Option(None, "--kelly", "-k", help="Kelly fraction override (e.g. 0.15)"),
    stop_loss: Optional[float] = typer.Option(None, "--stop-loss", help="Stop-loss fraction override (e.g. 0.2)"),
):
    """Start the 24/7 automated trading daemon."""
    from pm_bot.cli.daemon import daemon_start

    strat_names = [s.strip() for s in strategies.split(",") if s.strip()] if strategies else None

    if kelly is not None or stop_loss is not None:
        import os
        if kelly is not None:
            os.environ["PM_BOT_KELLY"] = str(kelly)
        if stop_loss is not None:
            os.environ.setdefault("PM_BOT_STOP_LOSS", str(stop_loss))

    asyncio.run(daemon_start(debug=debug, dry_run=dry_run, strategy_names=strat_names))


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


@app.command()
def backtest(
    strategy: Optional[str] = typer.Option(None, "--strategy", "-s", help="Strategy name"),
    all_strats: bool = typer.Option(False, "--all", help="Run all strategies"),
    compare: bool = typer.Option(False, "--compare", help="Side-by-side comparison"),
    bankroll: float = typer.Option(100.0, "--bankroll", "-b", help="Starting bankroll USD"),
    days: int = typer.Option(90, "--days", "-d", help="Days to backtest"),
    cities: Optional[str] = typer.Option("NYC", "--cities", "-c", help="Comma-separated cities"),
    csv: Optional[str] = typer.Option(None, "--csv", help="Export CSV to path"),
    real: bool = typer.Option(False, "--real", help="Use real Polymarket historical prices and resolved outcomes"),
    stop_loss: float = typer.Option(0.0, "--stop-loss", help="Stop-loss fraction of position (e.g. 0.5=50%)"),
    kelly: float = typer.Option(0.25, "--kelly", help="Kelly fraction (0.25=quarter, 0.5=half, 1.0=full)"),
    max_pos: float = typer.Option(0.10, "--max-pos", help="Max single position as fraction of bankroll"),
    no_compound: bool = typer.Option(False, "--no-compound", help="Disable compounding (fixed bankroll)"),
    live: bool = typer.Option(
        False, "--live", help="Live-trading mode: maker-only, $50/pos cap, 8%+ edge, ghost-trade friction"
    ),
    compare_forecast: bool = typer.Option(
        False, "--compare-forecast", help="Dual-run: all markets vs CLOB-only, showing forecast bias delta"
    ),
    forecast_penalty: float = typer.Option(
        0.05, "--forecast-penalty", help="Conservative penalty for forecast-derived prices (default: 0.05)"
    ),
    portfolio: bool = typer.Option(
        False, "--portfolio", help="Portfolio mode: all strategies share one bankroll, merged signals"
    ),
    seed: Optional[int] = typer.Option(None, "--seed", help="Random seed for deterministic FillModel sampling"),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
):
    """Run backtest against historical data."""
    from pm_bot.cli.backtest_cmd import _run_backtest

    asyncio.run(
        _run_backtest(
            strategy=strategy,
            all_strats=all_strats,
            compare=compare,
            bankroll=bankroll,
            days=days,
            cities_str=cities,
            csv_path=csv,
            real=real,
            stop_loss=stop_loss,
            kelly=kelly,
            max_pos=max_pos,
            no_compound=no_compound,
            live=live,
            compare_forecast=compare_forecast,
            forecast_penalty=forecast_penalty,
            portfolio=portfolio,
            seed=seed,
            debug=debug,
        )
    )
