"""Backtest for Smart Wallet Copy-Trading Strategy.

Tests whether copying profitable weather traders would have been profitable.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
import structlog

from pm_bot.core.smart_wallet import WalletTracker, SMART_WALLETS
from pm_bot.models.market import ForecastResult, TemperatureBucket, WeatherEvent

log = structlog.get_logger()

DATA_API_BASE = "https://data-api.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"


@dataclass
class HistoricalTrade:
    """A historical trade from a wallet."""

    trade_id: str
    wallet: str
    market_id: str
    token_id: str
    side: str
    price: float
    size: float
    timestamp: int
    city: str = ""
    bucket_question: str = ""
    outcome: str = ""  # "YES" or "NO"
    won: bool = False
    pnl: float = 0.0


@dataclass
class BacktestResult:
    """Result of a backtest."""

    strategy: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    win_rate: float
    avg_win: float
    avg_loss: float
    max_drawdown: float
    sharpe_ratio: float
    trades: list[HistoricalTrade] = field(default_factory=list)


class SmartWalletBacktester:
    """Backtest smart wallet copy-trading strategy."""

    def __init__(
        self,
        wallets: dict[str, dict] | None = None,
        days: int = 90,
        copy_delay_min: float = 5.0,
        min_trade_size: float = 5.0,
    ):
        self.wallets = wallets or SMART_WALLETS
        self.days = days
        self.copy_delay_min = copy_delay_min
        self.min_trade_size = min_trade_size

    async def fetch_historical_trades(
        self,
        client: httpx.AsyncClient,
        wallet: str,
        days: int = 90,
    ) -> list[dict]:
        """Fetch historical trades for a wallet."""
        trades = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_ts = int(cutoff.timestamp())

        offset = 0
        limit = 100
        while True:
            try:
                resp = await client.get(
                    f"{DATA_API_BASE}/trades",
                    params={
                        "user": wallet,
                        "limit": limit,
                        "offset": offset,
                        "takerOnly": "false",
                    },
                    timeout=30.0,
                )
                resp.raise_for_status()
                batch = resp.json()

                if not batch:
                    break

                for t in batch:
                    ts = t.get("timestamp", 0)
                    if ts > 1e12:
                        ts = ts / 1000

                    if ts < cutoff_ts:
                        return trades

                    trades.append(t)

                offset += limit

                # Stop if we got less than a full batch
                if len(batch) < limit:
                    break

            except httpx.HTTPError as e:
                log.error("trade_fetch_failed", wallet=wallet[:10], error=str(e))
                break

        return trades

    async def fetch_resolved_events(
        self,
        client: httpx.AsyncClient,
        days: int = 90,
    ) -> list[dict]:
        """Fetch resolved weather events."""
        events = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        for series_slug in self._get_weather_series_slugs():
            try:
                resp = await client.get(
                    f"{GAMMA_API_BASE}/events",
                    params={
                        "series_slug": series_slug,
                        "limit": 100,
                        "order": "end_date",
                        "ascending": "false",
                    },
                    timeout=15.0,
                )
                resp.raise_for_status()
                batch = resp.json()

                for ev in batch:
                    # Include all events (active and resolved)
                    # We'll filter by outcome prices later
                    events.append(ev)

            except httpx.HTTPError as e:
                log.debug("event_fetch_failed", series=series_slug, error=str(e))

        return events

    def _get_weather_series_slugs(self) -> list[str]:
        """Get weather series slugs."""
        slugs = []
        for city in [
            "new-york", "los-angeles", "miami", "chicago", "london",
            "tokyo", "hong-kong", "seoul", "taipei", "shanghai",
            "beijing", "paris", "berlin", "madrid", "rome",
            "sydney", "melbourne", "toronto", "vancouver", "mexico-city",
            "sao-paulo", "buenos-aires", "lagos", "cairo", "mumbai",
            "singapore", "bangkok", "jakarta", "istanbul", "moscow",
        ]:
            slugs.append(f"{city}-daily-weather")
        return slugs

    async def run_backtest(
        self,
        initial_bankroll: float = 100.0,
    ) -> BacktestResult:
        """Run backtest of smart wallet copy-trading."""
        log.info(
            "starting_smart_wallet_backtest",
            wallets=len(self.wallets),
            days=self.days,
            bankroll=initial_bankroll,
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Fetch historical trades from all wallets
            all_trades: list[HistoricalTrade] = []
            for wallet_addr, wallet_info in self.wallets.items():
                trades = await self.fetch_historical_trades(
                    client, wallet_addr, self.days
                )
                log.info(
                    "wallet_trades_fetched",
                    wallet=wallet_info["name"],
                    trades=len(trades),
                )

                # Convert to HistoricalTrade objects
                for t in trades:
                    ts = t.get("timestamp", 0)
                    if ts > 1e12:
                        ts = ts / 1000

                    # Only copy weather trades
                    title = t.get("title", "")
                    is_weather = any(
                        keyword in title.lower()
                        for keyword in ["temperature", "weather", "high", "low"]
                    )

                    if not is_weather:
                        continue

                    ht = HistoricalTrade(
                        trade_id=t.get("transactionHash", ""),
                        wallet=wallet_addr,
                        market_id=t.get("conditionId", ""),
                        token_id=t.get("asset", ""),
                        side=t.get("side", "BUY"),
                        price=float(t.get("price", 0)),
                        size=float(t.get("size", 0)),
                        timestamp=int(ts * 1000),
                        bucket_question=t.get("title", ""),
                        outcome=t.get("outcome", ""),
                    )
                    all_trades.append(ht)

            # Sort by timestamp
            all_trades.sort(key=lambda x: x.timestamp)

            # Fetch resolved events to determine outcomes
            resolved_events = await self.fetch_resolved_events(client, self.days)
            log.info("resolved_events_fetched", events=len(resolved_events))

            # Build market-to-outcome mapping
            market_outcomes = self._build_outcome_map(resolved_events)

            # Simulate copy-trading
            bankroll = initial_bankroll
            peak_bankroll = bankroll
            max_drawdown = 0.0
            winning_trades = 0
            losing_trades = 0
            total_pnl = 0.0
            pnl_history: list[float] = []

            for trade in all_trades:
                # Skip tiny trades
                if trade.size < self.min_trade_size:
                    continue

                # Skip sells (for now, only copy buys)
                if trade.side != "BUY":
                    continue

                # Look up outcome
                # Try matching by condition_id first, then by token
                outcome_info = None
                if trade.market_id in market_outcomes:
                    outcome_info = market_outcomes[trade.market_id]
                else:
                    # Try with token
                    outcome_key = f"{trade.market_id}:{trade.token_id}"
                    if outcome_key in market_outcomes:
                        outcome_info = market_outcomes[outcome_key]

                if outcome_info:
                    trade.city = outcome_info.get("city", "")
                    trade.bucket_question = outcome_info.get("question", "")

                    # Determine if this trade won
                    if trade.outcome == "Yes":
                        trade.won = outcome_info.get("won_yes", False)
                    else:
                        trade.won = not outcome_info.get("won_yes", False)

                    # Calculate P&L
                    if trade.won:
                        # Won: payout = (1 - price) * size
                        trade.pnl = trade.size * (1 - trade.price)
                        winning_trades += 1
                    else:
                        # Lost: lose the price * size
                        trade.pnl = -trade.size * trade.price
                        losing_trades += 1

                    total_pnl += trade.pnl
                    bankroll += trade.pnl

                    # Track drawdown
                    peak_bankroll = max(peak_bankroll, bankroll)
                    drawdown = (peak_bankroll - bankroll) / peak_bankroll
                    max_drawdown = max(max_drawdown, drawdown)

                    pnl_history.append(total_pnl)

            # Calculate metrics
            total = winning_trades + losing_trades
            win_rate = winning_trades / total if total > 0 else 0
            avg_win = (
                sum(t.pnl for t in all_trades if t.won) / winning_trades
                if winning_trades > 0
                else 0
            )
            avg_loss = (
                sum(t.pnl for t in all_trades if not t.won and t.pnl < 0) / losing_trades
                if losing_trades > 0
                else 0
            )

            # Calculate Sharpe (simplified)
            if pnl_history:
                import numpy as np

                returns = np.diff(pnl_history) / initial_bankroll
                sharpe = (
                    np.mean(returns) / np.std(returns) * np.sqrt(252)
                    if np.std(returns) > 0
                    else 0
                )
            else:
                sharpe = 0

            return BacktestResult(
                strategy="smart_wallet_copy",
                total_trades=total,
                winning_trades=winning_trades,
                losing_trades=losing_trades,
                total_pnl=total_pnl,
                win_rate=win_rate,
                avg_win=avg_win,
                avg_loss=avg_loss,
                max_drawdown=max_drawdown,
                sharpe_ratio=sharpe,
                trades=[t for t in all_trades if t.pnl != 0],
            )

    def _build_outcome_map(
        self, events: list[dict]
    ) -> dict[str, dict]:
        """Build mapping from market/token to outcome."""
        outcomes: dict[str, dict] = {}

        for ev in events:
            city = ev.get("title", "").split("on")[0].strip() if "on" in ev.get("title", "") else ""
            for market in ev.get("markets", []):
                condition_id = market.get("conditionId", "")
                question = market.get("question", "")

                # Determine winning outcome
                # For weather markets, check if YES won
                yes_won = False
                if market.get("outcomePrices"):
                    try:
                        import json
                        prices = json.loads(market["outcomePrices"])
                        if len(prices) >= 2:
                            yes_won = float(prices[0]) >= 0.99
                    except (json.JSONDecodeError, ValueError):
                        pass

                # Map by condition_id
                outcomes[condition_id] = {
                    "won_yes": yes_won,
                    "city": city,
                    "question": question,
                }

                # Map tokens
                if market.get("clobTokenIds"):
                    try:
                        import json
                        tokens = json.loads(market["clobTokenIds"])
                        if len(tokens) >= 2:
                            # YES token
                            outcomes[f"{condition_id}:{tokens[0]}"] = {
                                "won": yes_won,
                                "city": city,
                                "question": question,
                            }
                            # NO token
                            outcomes[f"{condition_id}:{tokens[1]}"] = {
                                "won": not yes_won,
                                "city": city,
                                "question": question,
                            }
                    except (json.JSONDecodeError, ValueError):
                        pass

        return outcomes


async def run_smart_wallet_backtest(
    days: int = 90,
    bankroll: float = 100.0,
) -> BacktestResult:
    """Run backtest and return results."""
    backtester = SmartWalletBacktester(days=days)
    return await backtester.run_backtest(initial_bankroll=bankroll)
