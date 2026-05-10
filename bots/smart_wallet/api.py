"""Polymarket Data API client for wallet tracking and trade monitoring.

Uses the public Data API (data-api.polymarket.com) and CLOB API (clob.polymarket.com)
to fetch trades, positions, and market data.

References:
- Data API trades: https://docs.polymarket.com/api-reference/trade/get-trades
- Data API positions: https://polymarket-data.com/data/positions?user=ADDRESS
- CLOB trades: https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx
import structlog

from pm_bot.smart_wallet.models import Side, Trade

logger = structlog.get_logger(__name__)

# API endpoints
DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# Rate limits
MAX_REQUESTS_PER_SECOND = 10
RETRY_DELAY = 1.0
MAX_RETRIES = 3


class PolymarketDataClient:
    """Client for Polymarket Data API — fetches trades, positions, market data."""

    def __init__(self, clob_api_key: Optional[str] = None, rate_limit: float = MAX_REQUESTS_PER_SECOND):
        self._clob_key = clob_api_key
        self._rate_limit = rate_limit
        self._last_request = 0.0
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> PolymarketDataClient:
        self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def _throttle(self) -> None:
        """Enforce rate limit."""
        now = time.monotonic()
        elapsed = now - self._last_request
        min_interval = 1.0 / self._rate_limit
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        self._last_request = time.monotonic()

    async def _get(self, url: str, params: Optional[dict] = None) -> Any:
        """GET with retry and rate limiting."""
        assert self._client is not None
        for attempt in range(MAX_RETRIES):
            await self._throttle()
            try:
                resp = await self._client.get(url, params=params)
                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", RETRY_DELAY * (attempt + 1)))
                    logger.warning("rate_limited", url=url, wait=wait)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (500, 502, 503, 504):
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                raise
            except httpx.RequestError:
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                raise
        raise RuntimeError(f"Failed after {MAX_RETRIES} retries: {url}")

    # ─── Market Data ──────────────────────────────────────────────────────

    async def get_markets(
        self,
        limit: int = 100,
        active: bool = True,
        closed: bool = False,
        slug: Optional[str] = None,
    ) -> list[dict]:
        """Fetch markets from Data API."""
        params: dict[str, Any] = {"limit": limit}
        if slug:
            params["slug"] = slug
        data = await self._get(f"{DATA_API}/markets", params=params)
        markets = data if isinstance(data, list) else data.get("data", [])
        result = []
        for m in markets:
            is_active = m.get("active", False) or m.get("enableOrderBook", False)
            is_closed = m.get("closed", False)
            if slug:
                result.append(m)
            elif active and not closed:
                if is_active and not is_closed:
                    result.append(m)
            elif closed:
                if is_closed:
                    result.append(m)
            else:
                result.append(m)
        return result

    async def get_market_by_slug(self, slug: str) -> Optional[dict]:
        """Fetch a single market by slug."""
        markets = await self.get_markets(slug=slug)
        return markets[0] if markets else None

    async def get_events(self, limit: int = 100, active: bool = True) -> list[dict]:
        """Fetch events (groups of markets)."""
        params: dict[str, Any] = {"limit": limit, "active": active}
        data = await self._get(f"{DATA_API}/events", params=params)
        return data if isinstance(data, list) else data.get("data", [])

    # ─── Trade Data ───────────────────────────────────────────────────────

    async def get_trades(
        self,
        market_id: Optional[str] = None,
        asset_id: Optional[str] = None,
        before: Optional[int] = None,
        after: Optional[int] = None,
        limit: int = 500,
    ) -> list[dict]:
        """Fetch trades from Data API with pagination."""
        all_trades: list[dict] = []
        cursor: Optional[str] = None

        while True:
            params: dict[str, Any] = {"limit": min(limit - len(all_trades), 500)}
            if market_id:
                params["market"] = market_id
            if asset_id:
                params["asset_id"] = asset_id
            if before:
                params["before"] = before
            if after:
                params["after"] = after
            if cursor:
                params["next_cursor"] = cursor

            data = await self._get(f"{DATA_API}/trades", params=params)
            trades = data.get("data", data) if isinstance(data, dict) else data
            if not isinstance(trades, list):
                break

            all_trades.extend(trades)
            cursor = data.get("next_cursor") if isinstance(data, dict) else None
            if not cursor or not trades or len(all_trades) >= limit:
                break

        return all_trades[:limit]

    async def get_trades_for_wallet(
        self,
        wallet_address: str,
        limit: int = 500,
        before: Optional[int] = None,
        after: Optional[int] = None,
    ) -> list[Trade]:
        """Fetch trades for a specific wallet using CLOB API.

        Uses the CLOB /trades endpoint with maker_address or taker_address filter,
        then enriches with market metadata from Data API.
        """
        params: dict[str, Any] = {
            "limit": limit,
            "maker_address": wallet_address,
        }
        if before:
            params["before"] = before
        if after:
            params["after"] = after

        data = await self._get(f"{CLOB_API}/trades", params=params)
        raw_trades = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(raw_trades, list):
            return []

        # Also fetch taker trades
        params_taker = {
            "limit": limit,
            "taker_address": wallet_address,
        }
        if before:
            params_taker["before"] = before
        if after:
            params_taker["after"] = after

        data_taker = await self._get(f"{CLOB_API}/trades", params=params_taker)
        raw_trades_taker = data_taker.get("data", data_taker) if isinstance(data_taker, dict) else data_taker
        if isinstance(raw_trades_taker, list):
            raw_trades.extend(raw_trades_taker)

        # Deduplicate by trade ID
        seen = set()
        unique_trades = []
        for t in raw_trades:
            tid = t.get("id", "")
            if tid not in seen:
                seen.add(tid)
                unique_trades.append(t)

        # Convert to Trade objects
        trades = []
        for t in unique_trades:
            try:
                price = float(t.get("price", 0))
                size_raw = float(t.get("size", 0))
                # CLOB size is in shares, price is per share
                trade = Trade(
                    trade_id=t.get("id", ""),
                    market_id=t.get("market", ""),
                    condition_id=t.get("market", ""),  # same as market_id in CLOB
                    slug=t.get("slug", ""),
                    title=t.get("title", ""),
                    outcome=t.get("outcome", ""),
                    outcome_index=int(t.get("outcomeIndex", 0)),
                    side=Side.BUY if t.get("side") == "BUY" else Side.SELL,
                    price=price,
                    size=size_raw,
                    timestamp=int(t.get("match_time", t.get("timestamp", 0))),
                    maker_address=t.get("maker_address", ""),
                    taker_address=t.get("taker_address", wallet_address),
                    transaction_hash=t.get("transaction_hash", ""),
                    fee_rate_bps=int(t.get("fee_rate_bps", "30")),
                )
                trades.append(trade)
            except (ValueError, KeyError) as e:
                logger.debug("skip_trade_parse", error=str(e), raw=t)
                continue

        return sorted(trades, key=lambda x: x.timestamp, reverse=True)

    # ─── Positions ────────────────────────────────────────────────────────

    async def get_positions_for_wallet(self, wallet_address: str) -> list[dict]:
        """Fetch open positions for a wallet from Data API."""
        data = await self._get(
            f"{DATA_API}/positions",
            params={"user": wallet_address, "sizeThreshold": "0"},
        )
        return data if isinstance(data, list) else data.get("data", [])

    # ─── Price History ────────────────────────────────────────────────────

    async def get_price_history(
        self,
        market_id: str,
        interval: str = "1d",
        fidelity: int = 60,
    ) -> list[dict]:
        """Fetch price history for a market (CLOB /prices-history)."""
        params = {"market": market_id, "interval": interval, "fidelity": fidelity}
        data = await self._get(f"{CLOB_API}/prices-history", params=params)
        return data if isinstance(data, list) else data.get("history", [])
