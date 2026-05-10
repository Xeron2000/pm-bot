"""Smart wallet identification and scoring algorithm.

Identifies wallets with sustained edge by analyzing trade history on closed markets.
A wallet is "smart" if it consistently generates risk-adjusted returns above baseline
across multiple independent markets.

Scoring methodology (v1 — composite_rank):
1. Win Rate (30%): % of resolved markets with positive PnL
2. Consistency (25%): Sharpe-like metric across resolved positions
3. Volume (20%): Total absolute volume (log-normalized)
4. Edge (25%): Average realized edge vs entry price on resolved markets

Reference: Polymarket data-api for trade history and position resolution.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import structlog

from pm_bot.smart_wallet.api import PolymarketDataClient
from pm_bot.smart_wallet.models import Trade, WalletProfile

logger = structlog.get_logger(__name__)

# Minimum thresholds for a wallet to be considered for scoring
MIN_TRADES = 10
MIN_VOLUME_USD = 1000.0
MIN_RESOLVED_MARKETS = 3
MAX_WALLET_AGE_DAYS = 30  # only wallets active in last 30 days


@dataclass
class MarketPosition:
    """Aggregated position for a wallet in a single market."""
    market_id: str
    slug: str
    title: str
    outcome: str
    total_size: float = 0.0
    avg_entry_price: float = 0.0
    total_cost: float = 0.0
    realized_pnl: float = 0.0
    is_resolved: bool = False
    resolution_price: Optional[float] = None  # 1.0 or 0.0

    def add_trade(self, trade: Trade) -> None:
        """Update position with a new trade."""
        if trade.side.value == "BUY":
            new_cost = self.total_cost + (trade.price * trade.size)
            self.total_size += trade.size
            self.avg_entry_price = new_cost / self.total_size if self.total_size > 0 else 0
            self.total_cost = new_cost
        else:  # SELL
            if self.total_size > 0:
                pnl_per_share = trade.price - self.avg_entry_price
                self.realized_pnl += pnl_per_share * trade.size
            self.total_size -= trade.size
            if self.total_size <= 0:
                self.total_size = 0
                self.total_cost = 0
                self.avg_entry_price = 0

    def resolve(self, outcome_won: bool) -> None:
        """Mark position as resolved."""
        self.is_resolved = True
        self.resolution_price = 1.0 if outcome_won else 0.0
        # Unrealized PnL becomes realized
        if self.total_size > 0:
            pnl_per_share = self.resolution_price - self.avg_entry_price
            self.realized_pnl += pnl_per_share * self.total_size


class SmartWalletTracker:
    """Identifies and ranks smart wallets on Polymarket."""

    def __init__(self, client: PolymarketDataClient):
        self._client = client
        self._wallet_cache: dict[str, WalletProfile] = {}

    async def scan_market_for_wallets(
        self,
        market_id: str,
        slug: str = "",
        title: str = "",
        limit: int = 2000,
    ) -> dict[str, list[Trade]]:
        """Fetch all trades for a market and group by wallet address."""
        raw_trades = await self._client.get_trades(market_id=market_id, limit=limit)

        wallets: dict[str, list[Trade]] = defaultdict(list)
        for t in raw_trades:
            try:
                maker = t.get("maker_address", "")
                taker = t.get("taker_address", "")
                price = float(t.get("price", 0))
                size_raw = float(t.get("size", 0))
                ts = int(t.get("match_time", t.get("timestamp", 0)))

                trade = Trade(
                    trade_id=t.get("id", ""),
                    market_id=market_id,
                    condition_id=market_id,
                    slug=slug,
                    title=title,
                    outcome=t.get("outcome", ""),
                    outcome_index=int(t.get("outcomeIndex", 0)),
                    side=t.get("side", "BUY"),
                    price=price,
                    size=size_raw,
                    timestamp=ts,
                    maker_address=maker,
                    taker_address=taker,
                    transaction_hash=t.get("transaction_hash", ""),
                )

                if maker:
                    wallets[maker].append(trade)
                if taker and taker != maker:
                    wallets[taker].append(trade)
            except (ValueError, KeyError):
                continue

        return dict(wallets)

    async def analyze_wallet(
        self,
        address: str,
        trades: Optional[list[Trade]] = None,
        resolved_markets: Optional[dict[str, bool]] = None,
    ) -> Optional[WalletProfile]:
        """Compute wallet profile from trade history.

        Args:
            address: Wallet address to analyze.
            trades: Pre-fetched trades (optional, will fetch if not provided).
            resolved_markets: Map of market_id -> outcome_won for resolved markets.
        """
        if trades is None:
            trades = await self._client.get_trades_for_wallet(address, limit=2000)

        if len(trades) < MIN_TRADES:
            return None

        # Aggregate positions by market
        positions: dict[str, MarketPosition] = {}
        for trade in reversed(trades):  # chronological order
            mid = trade.market_id
            if mid not in positions:
                positions[mid] = MarketPosition(
                    market_id=mid,
                    slug=trade.slug,
                    title=trade.title,
                    outcome=trade.outcome,
                )
            positions[mid].add_trade(trade)

        # Calculate stats
        total_volume = sum(abs(t.price * t.size) for t in trades)
        if total_volume < MIN_VOLUME_USD:
            return None

        # Mark resolved markets if we have resolution data
        resolved_count = 0
        pnl_values: list[float] = []
        winning_markets = 0

        for mid, pos in positions.items():
            if resolved_markets and mid in resolved_markets:
                pos.resolve(resolved_markets[mid])
                resolved_count += 1
                pnl_values.append(pos.realized_pnl)
                if pos.realized_pnl > 0:
                    winning_markets += 1

        if resolved_count < MIN_RESOLVED_MARKETS:
            logger.debug("wallet_too_few_resolved", address=address[:10], resolved=resolved_count)
            return None

        win_rate = winning_markets / resolved_count if resolved_count > 0 else 0
        avg_pnl = sum(pnl_values) / len(pnl_values) if pnl_values else 0
        pnl_std = (
            math.sqrt(sum((p - avg_pnl) ** 2 for p in pnl_values) / len(pnl_values))
            if len(pnl_values) > 1
            else 1.0
        )
        sharpe = avg_pnl / pnl_std if pnl_std > 0 else 0

        timestamps = [t.timestamp for t in trades]
        first_seen = datetime.utcfromtimestamp(min(timestamps)) if timestamps else None
        last_seen = datetime.utcfromtimestamp(max(timestamps)) if timestamps else None

        largest_trade = max((t.price * t.size for t in trades), default=0)

        # Composite score
        volume_norm = min(math.log10(total_volume + 1) / 6.0, 1.0)  # normalized to [0,1]
        edge_score = min(max(sharpe, 0) / 2.0, 1.0)  # cap at 2.0 sharpe

        # Weighted composite (higher = smarter)
        composite = (
            0.30 * win_rate +
            0.25 * min(max(sharpe, 0) / 2.0, 1.0) +
            0.20 * volume_norm +
            0.25 * edge_score
        )

        profile = WalletProfile(
            address=address,
            total_volume_usd=total_volume,
            total_pnl_usd=sum(pnl_values),
            win_rate=win_rate,
            num_markets=len(positions),
            num_trades=len(trades),
            avg_trade_size_usd=total_volume / len(trades) if trades else 0,
            largest_trade_usd=largest_trade,
            first_seen=first_seen,
            last_seen=last_seen,
            consistency_score=sharpe,
            volume_score=volume_norm,
            edge_score=edge_score,
            composite_score=composite,
        )

        self._wallet_cache[address] = profile
        return profile

    async def rank_wallets_from_market(
        self,
        market_id: str,
        slug: str = "",
        title: str = "",
        resolved_markets: Optional[dict[str, bool]] = None,
    ) -> list[WalletProfile]:
        """Scan a single market and rank all wallets found."""
        wallets_trades = await self.scan_market_for_wallets(market_id, slug, title)

        profiles = []
        for address, trades in wallets_trades.items():
            profile = await self.analyze_wallet(address, trades, resolved_markets)
            if profile:
                profiles.append(profile)
                await asyncio.sleep(0.1)  # gentle rate limiting

        profiles.sort(key=lambda p: p.composite_score, reverse=True)
        return profiles

    async def discover_smart_wallets(
        self,
        market_ids: list[str],
        top_n: int = 50,
        min_score: float = 0.5,
    ) -> list[WalletProfile]:
        """Discover smart wallets across multiple markets.

        This is the main discovery pipeline:
        1. Scan each market for wallet activity
        2. Aggregate and deduplicate wallets
        3. Score each wallet on their full history
        4. Return top N by composite score
        """
        all_addresses: set[str] = set()
        market_wallet_trades: dict[str, dict[str, list[Trade]]] = {}

        logger.info("discovering_wallets", markets=len(market_ids))

        for i, mid in enumerate(market_ids):
            wallets = await self.scan_market_for_wallets(mid)
            market_wallet_trades[mid] = wallets
            all_addresses.update(wallets.keys())
            if (i + 1) % 5 == 0:
                logger.info("scanned_markets", done=i + 1, total=len(market_ids), wallets=len(all_addresses))

        logger.info("found_wallets", count=len(all_addresses))

        # Analyze each wallet across all markets
        profiles = []
        for address in all_addresses:
            # Collect all trades for this wallet across all markets
            all_trades: list[Trade] = []
            for mid, wallet_trades in market_wallet_trades.items():
                if address in wallet_trades:
                    all_trades.extend(wallet_trades[address])

            profile = await self.analyze_wallet(address, all_trades)
            if profile and profile.composite_score >= min_score:
                profiles.append(profile)

        profiles.sort(key=lambda p: p.composite_score, reverse=True)
        top = profiles[:top_n]
        logger.info("smart_wallets_found", count=len(top), threshold=min_score)
        return top


def identify_smart_wallets_heuristic(
    trades: list[Trade],
    min_volume_usd: float = 10000.0,
    min_trades: int = 5,
) -> dict[str, float]:
    """Fast heuristic-based smart wallet scoring without API calls.

    Returns dict of address -> score based on:
    - Volume (higher = better signal)
    - Number of trades (more = more reliable)
    - Average trade size (larger = more conviction)

    This is useful for initial filtering before expensive API-based analysis.
    """
    wallet_stats: dict[str, dict[str, float]] = defaultdict(lambda: {
        "volume": 0.0, "trades": 0, "total_size": 0.0,
    })

    for t in trades:
        vol = abs(t.price * t.size)
        addr = t.taker_address or t.maker_address
        wallet_stats[addr]["volume"] += vol
        wallet_stats[addr]["trades"] += 1
        wallet_stats[addr]["total_size"] += t.size

    scores: dict[str, float] = {}
    for addr, stats in wallet_stats.items():
        if stats["trades"] < min_trades or stats["volume"] < min_volume_usd:
            continue
        # Log-normalized volume * sqrt(trades) as a rough smartness proxy
        vol_score = min(math.log10(stats["volume"] + 1) / 6.0, 1.0)
        trade_score = min(math.sqrt(stats["trades"]) / 20.0, 1.0)
        scores[addr] = 0.7 * vol_score + 0.3 * trade_score

    return dict(sorted(scores.items(), key=lambda x: x[1], reverse=True))
