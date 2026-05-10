"""CLI commands for the smart wallet copy-trading bot.

Commands:
    discover    — Scan closed markets to find smart wallets
    backtest    — Run backtest on historical data
    monitor     — Start live monitoring of tracked wallets
    status      — Show current bot status and tracked wallets
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="smart-wallet",
    help="Polymarket smart wallet copy-trading & inverse strategies",
    no_args_is_help=True,
)
console = Console()

DATA_DIR = Path("data")


@app.command()
def discover(
    markets: int = typer.Option(20, help="Number of closed markets to scan"),
    top: int = typer.Option(50, help="Number of top wallets to keep"),
    min_score: float = typer.Option(0.5, help="Minimum composite score"),
    output: Path = typer.Option(DATA_DIR / "smart_wallets.json", help="Output file"),
):
    """Discover smart wallets by analyzing closed market history."""
    from pm_bot.smart_wallet.api import PolymarketDataClient
    from pm_bot.smart_wallet.tracker import SmartWalletTracker
    from pm_bot.smart_wallet.monitor import save_wallet_profiles

    async def _run():
        async with PolymarketDataClient() as client:
            tracker = SmartWalletTracker(client)

            # Get closed markets
            console.print(f"[bold]Fetching {markets} closed markets...[/]")
            closed = await client.get_markets(closed=True, limit=markets)
            market_ids = [m.get("conditionId", m.get("id", "")) for m in closed]
            console.print(f"Found {len(market_ids)} closed markets")

            # Discover wallets
            console.print("[bold]Scanning for smart wallets...[/]")
            wallets = await tracker.discover_smart_wallets(
                market_ids=market_ids,
                top_n=top,
                min_score=min_score,
            )

            # Display results
            table = Table(title=f"Top {len(wallets)} Smart Wallets")
            table.add_column("Rank", justify="right")
            table.add_column("Address", max_width=15)
            table.add_column("Score", justify="right")
            table.add_column("Win Rate", justify="right")
            table.add_column("Volume", justify="right")
            table.add_column("PnL", justify="right")
            table.add_column("Markets", justify="right")

            for i, w in enumerate(wallets[:20], 1):
                table.add_row(
                    str(i),
                    f"{w.address[:10]}...",
                    f"{w.composite_score:.3f}",
                    f"{w.win_rate:.1%}",
                    f"${w.total_volume_usd:,.0f}",
                    f"${w.total_pnl_usd:+,.0f}",
                    str(w.num_markets),
                )
            console.print(table)

            # Save
            save_wallet_profiles(wallets, output)
            console.print(f"\n[green]Saved {len(wallets)} wallets to {output}[/]")

    asyncio.run(_run())


@app.command()
def backtest(
    wallet_file: Path = typer.Option(DATA_DIR / "smart_wallets.json", help="Wallet profiles file"),
    bankroll: float = typer.Option(1000.0, help="Starting bankroll in USD"),
    days: int = typer.Option(90, help="Backtest period in days"),
    strategy: str = typer.Option("copy", help="Strategy: copy or inverse"),
    slippage_bps: float = typer.Option(15, help="Base slippage in basis points"),
    latency_s: float = typer.Option(5, help="Assumed latency in seconds"),
    seed: int = typer.Option(42, help="Random seed for reproducibility"),
):
    """Run backtest on historical data with slippage and latency simulation."""
    from pm_bot.smart_wallet.api import PolymarketDataClient
    from pm_bot.smart_wallet.backtest import BacktestEngine, SlippageConfig, LatencyConfig
    from pm_bot.smart_wallet.models import StrategyType
    from pm_bot.smart_wallet.monitor import load_wallet_profiles
    from pm_bot.smart_wallet.strategy import CopyStrategy, InverseStrategy

    async def _run():
        wallets = load_wallet_profiles(wallet_file)
        if not wallets:
            console.print(f"[red]No wallets found in {wallet_file}. Run 'discover' first.[/]")
            sys.exit(1)

        console.print(f"[bold]Loaded {len(wallets)} wallets[/]")
        console.print(f"Strategy: {strategy} | Bankroll: ${bankroll} | Period: {days} days")
        console.print(f"Slippage: {slippage_bps} bps | Latency: {latency_s}s")

        async with PolymarketDataClient() as client:
            # Fetch historical trades for tracked wallets
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)

            all_signals = []
            price_data: dict[str, list[tuple[datetime, float]]] = {}

            console.print("[bold]Fetching historical trades...[/]")
            for i, wallet in enumerate(wallets[:10]):  # top 10 wallets
                trades = await client.get_trades_for_wallet(
                    wallet.address,
                    limit=500,
                )
                console.print(f"  {wallet.address[:10]}: {len(trades)} trades")

                for t in trades:
                    if t.timestamp < start_date.timestamp():
                        continue

                    from pm_bot.smart_wallet.models import CopySignal

                    if strategy == "copy" and t.side == Side.BUY:
                        sig = CopySignal(
                            wallet=wallet,
                            trade=t,
                            strategy=StrategyType.COPY,
                            confidence=wallet.composite_score,
                            target_price=t.price,
                            target_size_usd=t.size_usd,
                            reason=f"copy {wallet.address[:8]}",
                            timestamp=datetime.utcfromtimestamp(t.timestamp),
                        )
                        all_signals.append(sig)
                    elif strategy == "inverse" and t.side == Side.BUY:
                        sig = CopySignal(
                            wallet=wallet,
                            trade=t,
                            strategy=StrategyType.INVERSE,
                            confidence=wallet.composite_score * 0.8,
                            target_price=t.price,
                            target_size_usd=t.size_usd * 0.5,
                            reason=f"inverse {wallet.address[:8]}",
                            timestamp=datetime.utcfromtimestamp(t.timestamp),
                        )
                        all_signals.append(sig)

            if not all_signals:
                console.print("[red]No signals generated from historical data.[/]")
                sys.exit(1)

            console.print(f"Generated {len(all_signals)} signals")

            # Run backtest
            strat = CopyStrategy() if strategy == "copy" else InverseStrategy()
            engine = BacktestEngine(
                strategy=strat,
                slippage=SlippageConfig(base_bps=slippage_bps),
                latency=LatencyConfig(
                    signal_delay_min_s=latency_s * 0.4,
                    signal_delay_max_s=latency_s * 0.6,
                    network_latency_min_s=latency_s * 0.2,
                    network_latency_max_s=latency_s * 0.4,
                ),
                seed=seed,
            )

            result = engine.run(
                signals=all_signals,
                price_data=price_data,
                bankroll=bankroll,
                start_date=start_date,
                end_date=end_date,
            )

            # Display results
            table = Table(title="Backtest Results")
            table.add_column("Metric", style="bold")
            table.add_column("Value", justify="right")
            table.add_row("Strategy", strategy)
            table.add_row("Period", f"{start_date.date()} to {end_date.date()}")
            table.add_row("Initial Bankroll", f"${result.initial_bankroll:,.2f}")
            table.add_row("Final Bankroll", f"${result.final_bankroll:,.2f}")
            table.add_row("Total PnL", f"${result.total_pnl:+,.2f}")
            table.add_row("Total Return", f"{result.total_return_pct:+.1f}%")
            table.add_row("Win Rate", f"{result.win_rate:.1%}")
            table.add_row("Total Trades", str(result.total_trades))
            table.add_row("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
            table.add_row("Profit Factor", f"{result.profit_factor:.2f}")
            table.add_row("Max Drawdown", f"{result.max_drawdown_pct:.1f}%")
            table.add_row("Total Fees", f"${result.total_fees:,.2f}")
            table.add_row("Total Slippage", f"${result.total_slippage:,.2f}")
            table.add_row("Avg Trade PnL", f"${result.avg_trade_pnl:+,.2f}")
            console.print(table)

    asyncio.run(_run())


@app.command()
def monitor(
    wallet_file: Path = typer.Option(DATA_DIR / "smart_wallets.json", help="Wallet profiles file"),
    bankroll: float = typer.Option(1000.0, help="Available bankroll"),
    duration: int = typer.Option(3600, help="Monitoring duration in seconds"),
    poll_interval: float = typer.Option(10, help="Poll interval in seconds"),
    strategy: str = typer.Option("both", help="Strategy: copy, inverse, or both"),
):
    """Start live monitoring of tracked smart wallets."""
    from pm_bot.smart_wallet.api import PolymarketDataClient
    from pm_bot.smart_wallet.monitor import LiveMonitor, load_wallet_profiles
    from pm_bot.smart_wallet.strategy import CopyStrategy, InverseStrategy

    async def _run():
        wallets = load_wallet_profiles(wallet_file)
        if not wallets:
            console.print(f"[red]No wallets found in {wallet_file}. Run 'discover' first.[/]")
            sys.exit(1)

        console.print(f"[bold green]Starting live monitor[/]")
        console.print(f"Tracking {len(wallets)} wallets | Bankroll: ${bankroll}")
        console.print(f"Strategy: {strategy} | Poll: {poll_interval}s | Duration: {duration}s")

        async with PolymarketDataClient() as client:
            copy_strat = CopyStrategy() if strategy in ("copy", "both") else None
            inverse_strat = InverseStrategy() if strategy in ("inverse", "both") else None

            monitor = LiveMonitor(
                client=client,
                copy_strategy=copy_strat or CopyStrategy(),
                inverse_strategy=inverse_strat or InverseStrategy(),
                tracked_wallets=wallets,
                bankroll=bankroll,
                poll_interval=poll_interval,
            )

            await monitor.run(duration_seconds=duration)

            # Summary
            console.print(f"\n[bold]Monitoring complete. {len(monitor.signals)} signals generated.[/]")
            for sig in monitor.signals[:10]:
                console.print(f"  {sig.strategy.value}: {sig.reason} @ {sig.target_price:.3f}")

    asyncio.run(_run())


@app.command()
def status(
    wallet_file: Path = typer.Option(DATA_DIR / "smart_wallets.json"),
):
    """Show current bot status and tracked wallets."""
    from pm_bot.smart_wallet.monitor import load_wallet_profiles

    wallets = load_wallet_profiles(wallet_file)
    if not wallets:
        console.print("[yellow]No tracked wallets. Run 'discover' to find smart wallets.[/]")
        return

    table = Table(title=f"Tracked Smart Wallets ({len(wallets)})")
    table.add_column("Address", max_width=15)
    table.add_column("Score", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("Volume", justify="right")
    table.add_column("Markets", justify="right")

    for w in wallets[:30]:
        table.add_row(
            f"{w.address[:12]}...",
            f"{w.composite_score:.3f}",
            f"{w.win_rate:.1%}",
            f"${w.total_volume_usd:,.0f}",
            str(w.num_markets),
        )
    console.print(table)


if __name__ == "__main__":
    app()
