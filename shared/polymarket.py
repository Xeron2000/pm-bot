"""Shared Polymarket API client for all bots."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx


class PolymarketClient:
    """Shared async client for Polymarket APIs.
    
    Endpoints:
    - Data API: https://data-api.polymarket.com (no auth)
    - Gamma API: https://gamma-api.polymarket.com (no auth)
    - CLOB API: https://clob.polymarket.com (requires API key)
    """

    def __init__(self, timeout: float = 30.0):
        self._client = httpx.AsyncClient(timeout=timeout)
        self._last_request = 0.0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._client.aclose()

    async def _get(self, url: str, params: dict = None) -> Any:
        """GET with rate limiting and retry."""
        now = time.monotonic()
        elapsed = now - self._last_request
        if elapsed < 0.05:  # 20/s max
            await asyncio.sleep(0.05 - elapsed)
        self._last_request = time.monotonic()

        for attempt in range(3):
            try:
                resp = await self._client.get(url, params=params)
                if resp.status_code == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception:
                if attempt < 2:
                    await asyncio.sleep(1)
                    continue
                raise
        return {}

    # ─── Data API (no auth) ─────────────────────────────────────────

    async def get_trades(self, limit: int = 100, **kwargs) -> list[dict]:
        """Fetch trades from Data API."""
        data = await self._get(
            "https://data-api.polymarket.com/trades",
            params={"limit": limit, **kwargs},
        )
        return data if isinstance(data, list) else data.get("data", [])

    async def get_positions(self, user: str, **kwargs) -> list[dict]:
        """Fetch positions for a user."""
        data = await self._get(
            "https://data-api.polymarket.com/positions",
            params={"user": user, "sizeThreshold": "0", **kwargs},
        )
        return data if isinstance(data, list) else data.get("data", [])

    # ─── Gamma API (no auth) ────────────────────────────────────────

    async def get_markets(self, limit: int = 100, **kwargs) -> list[dict]:
        """Fetch markets from Gamma API."""
        data = await self._get(
            "https://gamma-api.polymarket.com/markets",
            params={"limit": limit, **kwargs},
        )
        return data if isinstance(data, list) else data.get("data", [])

    async def get_events(self, limit: int = 100, **kwargs) -> list[dict]:
        """Fetch events from Gamma API."""
        data = await self._get(
            "https://gamma-api.polymarket.com/events",
            params={"limit": limit, **kwargs},
        )
        return data if isinstance(data, list) else data.get("data", [])
