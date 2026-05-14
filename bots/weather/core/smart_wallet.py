"""Smart Wallet Tracking — Copy-trade profitable weather market wallets.

Monitors top Polymarket weather traders and generates signals based on their activity.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
import structlog

from pm_bot.models.config import CITY_COORDS

log = structlog.get_logger()

# Known profitable weather market wallets
SMART_WALLETS = {
    "0x594edb9112f526fa6a80b8f858a6379c8a2c1c11": {
        "name": "ColdMath",
        "pnl": 143_000,
        "style": "barbell",
        "description": "Secondary markets, tail buys + central bets",
    },
    "0xf2f6af4f27ec2dcf4072095ab804016e14cd5817": {
        "name": "gopfan2",
        "pnl": 182_000,
        "style": "tail_buy",
        "description": "Tail YES buys below $0.15",
    },
    "0x44c1DfE43260C94Ed4F1D00dE2e1f80Fb113Ebc1": {
        "name": "aenews2",
        "pnl": 79_000,
        "style": "forecast_arb",
        "description": "High win rate (84%), forecast arb style",
    },
    "0x331bf91c132af9d921e1908ca0979363fc47193f": {
        "name": "BeefSlayer",
        "pnl": 62_000,
        "style": "mixed",
        "description": "Mixed weather market strategy",
    },
}

# Cache for market-to-event mapping
_market_event_cache: dict[str, dict] = {}
_cache_ttl: float = 300.0  # 5 minutes
_cache_timestamp: float = 0.0

DATA_API_BASE = "https://data-api.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"


@dataclass
class WalletTrade:
    """A single trade from a tracked wallet."""

    trade_id: str
    wallet: str
    market_id: str
    token_id: str
    side: str  # "BUY" or "SELL"
    price: float
    size: float
    timestamp: int
    event_slug: str = ""
    bucket_question: str = ""

    @property
    def time_ago_min(self) -> float:
        """Minutes since trade."""
        # Handle both seconds and milliseconds timestamps
        ts = self.timestamp
        if ts > 1e12:  # Milliseconds
            ts = ts / 1000
        return (time.time() - ts) / 60


@dataclass
class SmartWalletSignal:
    """Signal generated from smart wallet activity."""

    wallet_name: str
    wallet_style: str
    trade: WalletTrade
    confidence: float  # 0-1
    reason: str


@dataclass
class WalletTracker:
    """Track and copy-trade smart money wallets."""

    tracked_wallets: dict[str, dict] = field(
        default_factory=lambda: SMART_WALLETS.copy()
    )
    recent_trades: dict[str, list[WalletTrade]] = field(default_factory=dict)
    signal_cooldown_min: float = 30.0  # Don't re-signal same market within 30min
    max_trade_age_min: float = 60.0  # Only consider trades < 60min old
    _last_signal: dict[str, float] = field(default_factory=dict)

    async def fetch_wallet_trades(
        self,
        client: httpx.AsyncClient,
        wallet: str,
        limit: int = 50,
    ) -> list[WalletTrade]:
        """Fetch recent trades for a wallet from Data API."""
        try:
            resp = await client.get(
                f"{DATA_API_BASE}/trades",
                params={"user": wallet, "limit": limit, "takerOnly": "false"},
                timeout=30.0,
            )
            resp.raise_for_status()
            trades_data = resp.json()

            trades = []
            for t in trades_data:
                # Parse trade
                side_raw = t.get("side", "")
                side = "BUY" if side_raw == "BUY" else "SELL"

                trade = WalletTrade(
                    trade_id=t.get("id", ""),
                    wallet=wallet,
                    market_id=t.get("market", ""),
                    token_id=t.get("asset_id", ""),
                    side=side,
                    price=float(t.get("price", 0)),
                    size=float(t.get("size", 0)),
                    timestamp=int(t.get("timestamp", 0)),
                )
                trades.append(trade)

            return trades

        except httpx.HTTPError as e:
            log.error("wallet_trade_fetch_failed", wallet=wallet[:10], error=str(e))
            return []

    async def fetch_event_for_market(
        self,
        client: httpx.AsyncClient,
        condition_id: str,
    ) -> dict | None:
        """Fetch event data for a market condition_id."""
        try:
            resp = await client.get(
                f"{GAMMA_API_BASE}/markets",
                params={"condition_id": condition_id},
                timeout=15.0,
            )
            resp.raise_for_status()
            markets = resp.json()
            if markets:
                return markets[0]
            return None
        except httpx.HTTPError:
            return None

    async def fetch_weather_events(
        self,
        client: httpx.AsyncClient,
    ) -> dict[str, list[dict]]:
        """Fetch all active weather events, indexed by city slug."""
        events_by_city: dict[str, list[dict]] = {}

        for series_slug in self._get_weather_series_slugs():
            try:
                resp = await client.get(
                    f"{GAMMA_API_BASE}/events",
                    params={
                        "series_slug": series_slug,
                        "limit": 20,
                        "order": "end_date",
                        "ascending": "false",
                    },
                    timeout=15.0,
                )
                resp.raise_for_status()
                events = resp.json()

                for ev in events:
                    if ev.get("active", 0) == 1:
                        city_slug = series_slug.replace("-daily-weather", "")
                        if city_slug not in events_by_city:
                            events_by_city[city_slug] = []
                        events_by_city[city_slug].append(ev)

            except httpx.HTTPError as e:
                log.debug("event_fetch_failed", series=series_slug, error=str(e))

        return events_by_city

    def _get_weather_series_slugs(self) -> list[str]:
        """Get weather series slugs for tracked cities."""
        slugs = []
        for city, coords in CITY_COORDS.items():
            city_slug = city.lower().replace(" ", "-").replace("(", "").replace(")", "")
            slugs.append(f"{city_slug}-daily-weather")
        return slugs

    async def scan_for_signals(
        self,
        client: httpx.AsyncClient,
        cities: list[str] | None = None,
        min_trade_size: float = 1.0,
    ) -> list[SmartWalletSignal]:
        """Scan tracked wallets for recent trades and generate signals."""
        signals: list[SmartWalletSignal] = []
        now = time.time()

        # Fetch recent trades from all tracked wallets
        all_trades: list[WalletTrade] = []
        for wallet_addr, wallet_info in self.tracked_wallets.items():
            trades = await self.fetch_wallet_trades(client, wallet_addr)
            all_trades.extend(trades)

        # Filter to recent trades only
        recent = [
            t
            for t in all_trades
            if t.time_ago_min < self.max_trade_age_min
            and t.size >= min_trade_size
        ]

        if not recent:
            log.info("no_recent_wallet_trades", age_min=self.max_trade_age_min)
            return signals

        # Fetch active weather events to map markets
        weather_events = await self.fetch_weather_events(client)

        # Process trades and generate signals
        for trade in recent:
            # Check cooldown
            market_key = f"{trade.market_id}:{trade.side}"
            last_sig = self._last_signal.get(market_key, 0)
            if now - last_sig < self.signal_cooldown_min * 60:
                continue

            # Try to find the event this trade belongs to
            event_info = await self._find_event_for_trade(
                client, trade, weather_events
            )

            if event_info is None:
                continue  # Not a weather trade

            # Generate signal
            wallet_info = self.tracked_wallets[trade.wallet]
            confidence = self._compute_confidence(trade, wallet_info)
            reason = self._build_reason(trade, wallet_info)

            signal = SmartWalletSignal(
                wallet_name=wallet_info["name"],
                wallet_style=wallet_info["style"],
                trade=trade,
                confidence=confidence,
                reason=reason,
            )
            signals.append(signal)
            self._last_signal[market_key] = now

            log.info(
                "smart_wallet_signal",
                wallet=signal.wallet_name,
                side=trade.side,
                price=trade.price,
                size=trade.size,
                confidence=confidence,
            )

        return signals

    async def _find_event_for_trade(
        self,
        client: httpx.AsyncClient,
        trade: WalletTrade,
        weather_events: dict[str, list[dict]],
    ) -> dict | None:
        """Find which weather event a trade belongs to.

        Uses a cache to avoid repeated API calls for the same market.
        """
        global _market_event_cache, _cache_timestamp

        # Check cache first
        cache_key = f"{trade.market_id}:{trade.token_id}"
        if cache_key in _market_event_cache:
            cached = _market_event_cache[cache_key]
            if time.time() - cached.get("timestamp", 0) < _cache_ttl:
                return cached.get("event_info")

        # Check each active weather event
        for city_slug, events in weather_events.items():
            for ev in events:
                for market in ev.get("markets", []):
                    # Try matching by condition_id
                    if market.get("conditionId") == trade.market_id:
                        event_info = {
                            "event": ev,
                            "market": market,
                            "city_slug": city_slug,
                        }
                        _market_event_cache[cache_key] = {
                            "event_info": event_info,
                            "timestamp": time.time(),
                        }
                        return event_info

                    # Try matching by token_id
                    if market.get("clobTokenIds"):
                        tokens = market["clobTokenIds"]
                        if isinstance(tokens, str):
                            import json

                            try:
                                tokens = json.loads(tokens)
                            except json.JSONDecodeError:
                                continue

                        if trade.token_id in tokens:
                            event_info = {
                                "event": ev,
                                "market": market,
                                "city_slug": city_slug,
                            }
                            _market_event_cache[cache_key] = {
                                "event_info": event_info,
                                "timestamp": time.time(),
                            }
                            return event_info

        # Cache miss
        _market_event_cache[cache_key] = {
            "event_info": None,
            "timestamp": time.time(),
        }
        return None

    def _compute_confidence(
        self, trade: WalletTrade, wallet_info: dict
    ) -> float:
        """Compute confidence score for a signal."""
        base = 0.5

        # Higher confidence for larger trades
        if trade.size >= 100:
            base += 0.2
        elif trade.size >= 20:
            base += 0.1

        # Higher confidence for more profitable wallets
        pnl = wallet_info.get("pnl", 0)
        if pnl >= 100_000:
            base += 0.2
        elif pnl >= 50_000:
            base += 0.1

        # Lower confidence for sells (could be profit-taking or stop-loss)
        if trade.side == "SELL":
            base -= 0.1

        # Lower confidence for old trades
        if trade.time_ago_min > 30:
            base -= 0.1

        return max(0.1, min(1.0, base))

    def _build_reason(
        self, trade: WalletTrade, wallet_info: dict
    ) -> str:
        """Build human-readable reason for signal."""
        style = wallet_info.get("style", "unknown")
        name = wallet_info.get("name", "unknown")

        parts = [f"{name} ({style})"]
        parts.append(f"{trade.side} @ ${trade.price:.3f}")
        parts.append(f"${trade.size:.0f}")
        parts.append(f"{trade.time_ago_min:.0f}min ago")

        return " | ".join(parts)

    def get_recent_signals(
        self, max_age_min: float = 60.0
    ) -> list[SmartWalletSignal]:
        """Get signals generated in the last N minutes."""
        # This would return cached signals from the last scan
        return []
