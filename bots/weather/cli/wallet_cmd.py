"""CLI for smart wallet tracking and copy-trading."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pm_bot.core.smart_wallet import WalletTracker, SMART_WALLETS

console = Console()


async def scan_wallets(
    cities: list[str] | None = None,
    min_confidence: float = 0.5,
    max_age_min: float = 60.0,
    min_trade_size: float = 1.0,
) -> None:
    """Scan tracked wallets for recent trades."""
    tracker = WalletTracker()

    console.print(
        Panel.fit(
            f"[bold cyan]Smart Wallet Scanner[/]\n"
            f"Tracking {len(tracker.tracked_wallets)} wallets | "
            f"Max age: {max_age_min}min | "
            f"Min confidence: {min_confidence}",
            border_style="cyan",
        )
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Fetch recent trades
        all_trades = []
        for wallet_addr, wallet_info in tracker.tracked_wallets.items():
            trades = await tracker.fetch_wallet_trades(client, wallet_addr)
            all_trades.extend(
                (t, wallet_info) for t in trades
            )

        # Filter to recent trades
        recent = [
            (t, info)
            for t, info in all_trades
            if t.time_ago_min < max_age_min and t.size >= min_trade_size
        ]

        if not recent:
            console.print("[yellow]No recent trades from tracked wallets.[/]")
            return

        # Display trades
        table = Table(title="Recent Smart Wallet Trades")
        table.add_column("Wallet", style="cyan")
        table.add_column("Style", style="magenta")
        table.add_column("Side", style="bold")
        table.add_column("Price", justify="right")
        table.add_column("Size", justify="right")
        table.add_column("Age (min)", justify="right")
        table.add_column("Trade ID", style="dim")

        for trade, info in sorted(recent, key=lambda x: x[0].timestamp, reverse=True):
            side_color = "green" if trade.side == "BUY" else "red"
            table.add_row(
                info["name"],
                info["style"],
                f"[{side_color}]{trade.side}[/]",
                f"${trade.price:.3f}",
                f"${trade.size:.0f}",
                f"{trade.time_ago_min:.0f}",
                trade.trade_id[:12] + "...",
            )

        console.print(table)

        # Summary
        total_buys = sum(1 for t, _ in recent if t.side == "BUY")
        total_sells = sum(1 for t, _ in recent if t.side == "SELL")
        total_volume = sum(t.size for t, _ in recent)

        console.print(
            f"\n[bold]Summary:[/] "
            f"{len(recent)} trades | "
            f"{total_buys} buys, {total_sells} sells | "
            f"${total_volume:,.0f} total volume"
        )


async def show_wallets() -> None:
    """Show tracked wallets and their stats."""
    table = Table(title="Tracked Smart Wallets")
    table.add_column("Name", style="cyan")
    table.add_column("Address", style="dim")
    table.add_column("Style", style="magenta")
    table.add_column("P&L", justify="right", style="green")
    table.add_column("Description")

    for addr, info in SMART_WALLETS.items():
        table.add_row(
            info["name"],
            addr[:10] + "...",
            info["style"],
            f"${info['pnl']:,.0f}",
            info["description"],
        )

    console.print(table)


async def monitor_wallets(
    interval_sec: float = 30.0,
    max_age_min: float = 30.0,
    min_trade_size: float = 5.0,
) -> None:
    """Continuously monitor wallets for new trades."""
    tracker = WalletTracker()

    console.print(
        Panel.fit(
            f"[bold cyan]Smart Wallet Monitor[/]\n"
            f"Tracking {len(tracker.tracked_wallets)} wallets | "
            f"Interval: {interval_sec}s | "
            f"Max age: {max_age_min}min",
            border_style="cyan",
        )
    )

    seen_trades: set[str] = set()

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                # Fetch trades
                all_trades = []
                for wallet_addr, wallet_info in tracker.tracked_wallets.items():
                    trades = await tracker.fetch_wallet_trades(client, wallet_addr)
                    all_trades.extend(
                        (t, wallet_info) for t in trades
                    )

                # Find new trades
                new_trades = []
                for trade, info in all_trades:
                    if (
                        trade.trade_id not in seen_trades
                        and trade.time_ago_min < max_age_min
                        and trade.size >= min_trade_size
                    ):
                        new_trades.append((trade, info))
                        seen_trades.add(trade.trade_id)

                # Display new trades
                for trade, info in new_trades:
                    side_color = "green" if trade.side == "BUY" else "red"
                    console.print(
                        f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] "
                        f"[cyan]{info['name']}[/] "
                        f"[{side_color}]{trade.side}[/] "
                        f"@ ${trade.price:.3f} "
                        f"(${trade.size:.0f})"
                    )

                # Wait for next scan
                await asyncio.sleep(interval_sec)

            except KeyboardInterrupt:
                console.print("\n[yellow]Monitor stopped.[/]")
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/]")
                await asyncio.sleep(interval_sec)
