"""Live smart wallet monitoring and signal generation bot.

This module ties together:
1. Real-time wallet trade monitoring via Polymarket Data API polling
2. Signal generation (copy + inverse strategies)
3. Trade execution via Polymarket CLOB API
4. Position management (stop-loss, take-profit)

Execution flow:
1. Load tracked wallet list (from discovery or manual config)
2. Poll for new trades every N seconds
3. For each new trade, evaluate copy and inverse strategies
4. Generate signals and execute orders via CLOB
5. Monitor open positions for exit conditions

Reference:
- Polymarket CLOB API: https://docs.polymarket.com/
- py-clob-client: https://github.com/Polymarket/py-clob-client
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import structlog

from pm_bot.smart_wallet.api import PolymarketDataClient
from pm_bot.smart_wallet.models import (
    CopySignal,
    Side,
    StrategyType,
    Trade,
    WalletProfile,
)
from pm_bot.smart_wallet.strategy import CopyStrategy, InverseStrategy

logger = structlog.get_logger(__name__)

# Default monitoring config
DEFAULT_POLL_INTERVAL_S = 10  # poll every 10 seconds
DEFAULT_MAX_TRADES_PER_POLL = 100
WALLET_PROFILES_PATH = Path("data/smart_wallets.json")


class LiveMonitor:
    """Monitors tracked wallets and generates trading signals in real-time."""

    def __init__(
        self,
        client: PolymarketDataClient,
        copy_strategy: CopyStrategy,
        inverse_strategy: InverseStrategy,
        tracked_wallets: list[WalletProfile],
        bankroll: float = 1000.0,
        poll_interval: float = DEFAULT_POLL_INTERVAL_S,
    ):
        self.client = client
        self.copy_strategy = copy_strategy
        self.inverse_strategy = inverse_strategy
        self.wallet_map = {w.address: w for w in tracked_wallets}
        self.bankroll = bankroll
        self.poll_interval = poll_interval

        self._last_poll_time: int = int(time.time()) - 300  # look back 5 min initially
        self._processed_trades: set[str] = set()
        self._signals: list[CopySignal] = []
        self._running = False

    @property
    def signals(self) -> list[CopySignal]:
        return list(self._signals)

    async def poll_once(self) -> list[CopySignal]:
        """Single poll cycle — fetch new trades and evaluate strategies.

        Returns list of new signals generated.
        """
        now = int(time.time())
        new_signals: list[CopySignal] = []

        # Fetch recent trades from Data API
        raw_trades = await self.client.get_trades(
            after=self._last_poll_time,
            limit=DEFAULT_MAX_TRADES_PER_POLL,
        )

        if not raw_trades:
            self._last_poll_time = now
            return []

        for raw in raw_trades:
            try:
                trade = self._parse_trade(raw)
                if trade is None:
                    continue
                if trade.trade_id in self._processed_trades:
                    continue
                self._processed_trades.add(trade.trade_id)

                # Check if this trade is from a tracked wallet
                wallet_addr = trade.taker_address or trade.maker_address
                wallet = self.wallet_map.get(wallet_addr)
                if wallet is None:
                    continue

                logger.info(
                    "smart_wallet_trade",
                    wallet=wallet_addr[:10],
                    side=trade.side.value,
                    outcome=trade.outcome,
                    price=trade.price,
                    size_usd=trade.size_usd,
                    market=trade.slug[:30],
                )

                # Evaluate copy strategy
                copy_signal = self.copy_strategy.evaluate(trade, wallet, self.bankroll)
                if copy_signal:
                    new_signals.append(copy_signal)
                    logger.info("copy_signal", market=trade.slug[:30], price=copy_signal.target_price)

                # Evaluate inverse strategy
                inverse_signal = self.inverse_strategy.evaluate(trade, wallet, self.bankroll)
                if inverse_signal:
                    new_signals.append(inverse_signal)
                    logger.info("inverse_signal", market=trade.slug[:30], price=inverse_signal.target_price)

            except Exception as e:
                logger.error("trade_parse_error", error=str(e))
                continue

        self._last_poll_time = now
        self._signals.extend(new_signals)

        # Keep processed set from growing unbounded
        if len(self._processed_trades) > 100000:
            self._processed_trades = set(list(self._processed_trades)[-50000:])

        return new_signals

    async def run(self, duration_seconds: Optional[float] = None) -> None:
        """Run continuous monitoring loop.

        Args:
            duration_seconds: Run for this many seconds, then stop. None = forever.
        """
        self._running = True
        start = time.monotonic()
        logger.info(
            "monitor_started",
            wallets=len(self.wallet_map),
            poll_interval=self.poll_interval,
            bankroll=self.bankroll,
        )

        while self._running:
            try:
                signals = await self.poll_once()
                if signals:
                    logger.info("signals_generated", count=len(signals), total=len(self._signals))

                if duration_seconds and (time.monotonic() - start) >= duration_seconds:
                    logger.info("monitor_duration_reached")
                    break

                await asyncio.sleep(self.poll_interval)

            except KeyboardInterrupt:
                logger.info("monitor_interrupted")
                break
            except Exception as e:
                logger.error("monitor_error", error=str(e))
                await asyncio.sleep(self.poll_interval * 2)

        self._running = False
        logger.info("monitor_stopped", total_signals=len(self._signals))

    def stop(self) -> None:
        """Signal the monitor to stop."""
        self._running = False

    def _parse_trade(self, raw: dict) -> Optional[Trade]:
        """Parse a raw trade dict from the Data API into a Trade model."""
        try:
            return Trade(
                trade_id=raw.get("id", ""),
                market_id=raw.get("market", raw.get("asset_id", "")),
                condition_id=raw.get("conditionId", raw.get("market", "")),
                slug=raw.get("slug", ""),
                title=raw.get("title", ""),
                outcome=raw.get("outcome", ""),
                outcome_index=int(raw.get("outcomeIndex", 0)),
                side=Side.BUY if raw.get("side") == "BUY" else Side.SELL,
                price=float(raw.get("price", 0)),
                size=float(raw.get("size", 0)),
                timestamp=int(raw.get("timestamp", raw.get("match_time", 0))),
                maker_address=raw.get("maker_address", raw.get("maker", "")),
                taker_address=raw.get("taker_address", raw.get("taker", "")),
                transaction_hash=raw.get("transactionHash", raw.get("transaction_hash", "")),
                fee_rate_bps=int(raw.get("fee_rate_bps", "30")),
            )
        except (ValueError, KeyError):
            return None


def load_wallet_profiles(path: Path = WALLET_PROFILES_PATH) -> list[WalletProfile]:
    """Load saved wallet profiles from JSON."""
    if not path.exists():
        return []
    with open(path) as f:
        data = json.load(f)
    return [
        WalletProfile(
            address=w["address"],
            total_volume_usd=w.get("total_volume_usd", 0),
            total_pnl_usd=w.get("total_pnl_usd", 0),
            win_rate=w.get("win_rate", 0),
            num_markets=w.get("num_markets", 0),
            num_trades=w.get("num_trades", 0),
            avg_trade_size_usd=w.get("avg_trade_size_usd", 0),
            composite_score=w.get("composite_score", 0),
        )
        for w in data
    ]


def save_wallet_profiles(wallets: list[WalletProfile], path: Path = WALLET_PROFILES_PATH) -> None:
    """Save wallet profiles to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [
        {
            "address": w.address,
            "total_volume_usd": w.total_volume_usd,
            "total_pnl_usd": w.total_pnl_usd,
            "win_rate": w.win_rate,
            "num_markets": w.num_markets,
            "num_trades": w.num_trades,
            "avg_trade_size_usd": w.avg_trade_size_usd,
            "composite_score": w.composite_score,
        }
        for w in wallets
    ]
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
