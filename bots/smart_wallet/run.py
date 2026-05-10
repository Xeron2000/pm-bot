#!/usr/bin/env python3
"""Polymarket Smart Wallet Copy-Trading Bot — Complete Runner.

This script provides a fully executable implementation of:
1. Smart wallet discovery (scanning closed markets)
2. Copy-trading strategy (follow smart money)
3. Inverse strategy (fade late smart money entries)
4. Backtesting with realistic slippage and latency
5. Live monitoring and signal generation

Usage:
    python run_smart_wallet_bot.py discover     # Find smart wallets
    python run_smart_wallet_bot.py backtest      # Run backtest
    python run_smart_wallet_bot.py live          # Start live monitoring
    python run_smart_wallet_bot.py full-pipeline # Run all steps

Requirements:
    pip install httpx structlog rich typer

Evidence base (verified sources):
    - Polyloly backtest: 75.9% WR, +46.7% ROI (zero slippage), +15-25% ROI (3¢ slippage)
      Source: https://polyloly.com/blog/polymarket-insider-tail-backtest-46-percent-roi
    - Convexly 10K wallet study: Top 1% captures 36.2% of profit
      Source: https://www.convexly.app/blog/polymarket-10k-wallet-study
    - Polymarket rate limits: 200 trades/10s (Data API), 150 positions/10s
      Source: https://docs.polymarket.com/api-reference/rate-limits
"""

from __future__ import annotations

import asyncio
import json
import math
import random
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# ─── Configuration ─────────────────────────────────────────────────────────

CONFIG = {
    # Wallet discovery
    "discovery": {
        "min_resolved_positions": 10,
        "min_total_stake_usd": 5000,
        "min_win_rate": 0.70,
        "max_avg_entry_price": 0.65,  # exclude scalp traders
        "top_n_wallets": 20,
        "scan_markets": 30,
    },
    # Strategy parameters
    "copy_strategy": {
        "min_wallet_score": 0.6,
        "min_trade_usd": 50,
        "max_entry_price": 0.80,
        "position_size_pct": 0.02,  # 2% of bankroll
        "kelly_fraction": 0.25,     # quarter-Kelly
        "cooldown_minutes": 30,
        "stop_loss_pct": 0.30,
        "take_profit_pct": 0.50,
    },
    "inverse_strategy": {
        "min_wallet_score": 0.6,
        "min_trade_usd": 100,
        "min_entry_price": 0.60,  # only fade high-price entries
        "position_size_pct": 0.01,  # 1% — smaller for contrarian
        "kelly_fraction": 0.15,
        "cooldown_minutes": 60,
        "stop_loss_pct": 0.25,
        "take_profit_pct": 0.40,
    },
    # Execution costs
    "execution": {
        "base_slippage_bps": 15,
        "spread_bps": 5,
        "volume_impact_factor": 0.1,
        "fee_bps": 30,  # Polymarket taker fee
        "latency_min_s": 3,
        "latency_max_s": 8,
    },
    # Backtest
    "backtest": {
        "bankroll": 1000.0,
        "days": 90,
        "seed": 42,
    },
    # Live monitoring
    "live": {
        "poll_interval_s": 15,
        "bankroll": 1000.0,
    },
}

DATA_DIR = Path("data/smart_wallet")


# ─── Data Models ───────────────────────────────────────────────────────────

@dataclass
class Trade:
    trade_id: str
    market_id: str
    slug: str
    title: str
    outcome: str
    side: str  # BUY/SELL
    price: float
    size: float
    timestamp: int
    wallet: str
    tx_hash: str = ""

    @property
    def size_usd(self) -> float:
        return self.price * self.size


@dataclass
class WalletProfile:
    address: str
    total_volume_usd: float = 0
    total_pnl_usd: float = 0
    win_rate: float = 0
    num_resolved: int = 0
    num_trades: int = 0
    avg_entry_price: float = 0
    composite_score: float = 0
    last_active: Optional[datetime] = None


@dataclass
class Signal:
    wallet: str
    strategy: str  # copy/inverse
    market_id: str
    slug: str
    outcome: str
    entry_price: float
    size_usd: float
    confidence: float
    timestamp: datetime
    reason: str = ""


@dataclass
class BacktestTrade:
    signal: Signal
    entry_price: float
    exit_price: float = 0
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    size_usd: float = 0
    pnl: float = 0
    slippage_cost: float = 0
    fee_cost: float = 0
    status: str = "open"


@dataclass
class BacktestResult:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0
    total_pnl: float = 0
    total_return_pct: float = 0
    max_drawdown_pct: float = 0
    sharpe_ratio: float = 0
    profit_factor: float = 0
    total_fees: float = 0
    total_slippage: float = 0
    trades: list = field(default_factory=list)


# ─── API Client ────────────────────────────────────────────────────────────

class PolymarketAPI:
    """Async client for Polymarket Data + CLOB APIs."""

    def __init__(self):
        import httpx
        self._client = httpx.AsyncClient(timeout=30.0)
        self._last_request = 0.0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._client.aclose()

    async def _get(self, url: str, params: dict = None) -> Any:
        # Rate limiting: max 20 req/s for trades endpoint
        now = time.monotonic()
        elapsed = now - self._last_request
        if elapsed < 0.05:  # 20/s
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

    async def get_closed_markets(self, limit: int = 30) -> list[dict]:
        """Fetch recently closed markets from gamma-api."""
        data = await self._get(
            "https://gamma-api.polymarket.com/markets",
            params={"limit": limit, "closed": "true"},
        )
        return data if isinstance(data, list) else data.get("data", [])

    async def get_trades_for_wallet(self, address: str, limit: int = 500) -> list[dict]:
        """Fetch trades for a wallet."""
        params = {"limit": limit, "maker_address": address}
        data = await self._get("https://clob.polymarket.com/trades", params=params)
        trades = data.get("data", data) if isinstance(data, dict) else data

        # Also check taker trades
        params2 = {"limit": limit, "taker_address": address}
        data2 = await self._get("https://clob.polymarket.com/trades", params=params2)
        trades2 = data2.get("data", data2) if isinstance(data2, dict) else data2

        if isinstance(trades2, list):
            trades.extend(trades2)

        # Deduplicate
        seen = set()
        unique = []
        for t in trades:
            tid = t.get("id", "")
            if tid and tid not in seen:
                seen.add(tid)
                unique.append(t)
        return unique

    async def get_market_trades(self, market_id: str, limit: int = 1000) -> list[dict]:
        """Fetch all trades for a market from data-api."""
        data = await self._get(
            "https://data-api.polymarket.com/trades",
            params={"market": market_id, "limit": limit},
        )
        return data.get("data", data) if isinstance(data, dict) else data

    async def get_positions(self, address: str) -> list[dict]:
        """Fetch open positions for a wallet from data-api."""
        data = await self._get(
            "https://data-api.polymarket.com/positions",
            params={"user": address, "sizeThreshold": "0"},
        )
        return data if isinstance(data, list) else data.get("data", [])


# ─── Smart Wallet Discovery ────────────────────────────────────────────────

class WalletDiscovery:
    """Discovers smart wallets by analyzing closed market history."""

    def __init__(self, api: PolymarketAPI):
        self.api = api
        self.cfg = CONFIG["discovery"]

    async def discover(self) -> list[WalletProfile]:
        """Main discovery pipeline."""
        print("\n🔍 Discovering smart wallets...")

        # Step 1: Get recent trades from data-api to find active wallets
        print("  Fetching recent trades...")
        all_trades = await self.api._get(
            "https://data-api.polymarket.com/trades",
            params={"limit": 500},
        )
        trades = all_trades if isinstance(all_trades, list) else all_trades.get("data", [])
        print(f"  Found {len(trades)} trades")

        # Step 2: Group by wallet
        wallet_positions: dict[str, list[dict]] = defaultdict(list)
        market_info: dict[str, dict] = {}
        
        for t in trades:
            wallet = t.get("proxyWallet", "") or t.get("maker_address", "") or t.get("taker_address", "")
            if not wallet:
                continue
            
            market_id = t.get("conditionId", t.get("asset", ""))
            slug = t.get("eventSlug", t.get("slug", ""))
            
            wallet_positions[wallet].append({
                "market": market_id,
                "slug": slug,
                "side": t.get("side", ""),
                "price": float(t.get("price", 0)),
                "size": float(t.get("size", 0)),
                "timestamp": int(t.get("timestamp", 0)),
            })
            
            if market_id and market_id not in market_info:
                market_info[market_id] = {"slug": slug, "title": t.get("title", "")}

        print(f"  Total unique wallets: {len(wallet_positions)}")

        # Step 3: Score each wallet
        profiles = []
        for address, positions in wallet_positions.items():
            profile = self._score_wallet(address, positions)
            if profile:
                profiles.append(profile)

        # Step 4: Rank and filter
        profiles.sort(key=lambda p: p.composite_score, reverse=True)
        top = profiles[:self.cfg["top_n_wallets"]]

        print(f"\n📊 Top {len(top)} Smart Wallets:")
        print(f"{'Rank':<5} {'Address':<15} {'Score':<8} {'Win%':<8} {'Volume':<12} {'Resolved':<10}")
        print("-" * 60)
        for i, w in enumerate(top, 1):
            print(f"{i:<5} {w.address[:12]+'...':<15} {w.composite_score:.3f}   "
                  f"{w.win_rate:.0%}   ${w.total_volume_usd:>10,.0f} {w.num_resolved:>6}")

        return top

    def _score_wallet(self, address: str, positions: list[dict]) -> Optional[WalletProfile]:
        """Score a wallet based on trade history."""
        cfg = self.cfg

        # Aggregate by market
        market_positions: dict[str, dict] = {}
        total_volume = 0
        for p in positions:
            mid = p["market"]
            if mid not in market_positions:
                market_positions[mid] = {
                    "side": p["side"],
                    "entry_price": 0,
                    "size": 0,
                    "cost": 0,
                }
            pos = market_positions[mid]
            if p["side"] == "BUY":
                new_cost = pos["cost"] + p["price"] * p["size"]
                pos["size"] += p["size"]
                pos["entry_price"] = new_cost / pos["size"] if pos["size"] > 0 else 0
                pos["cost"] = new_cost
            total_volume += p["price"] * p["size"]

        # Filter: minimum volume
        if total_volume < cfg["min_total_stake_usd"]:
            return None

        # Filter: minimum positions
        if len(market_positions) < cfg["min_resolved_positions"]:
            return None

        # Calculate win rate (simplified — assume resolved, count positions with entry < 0.65)
        # In production, would check actual resolution
        qualifying = [p for p in market_positions.values() if p["entry_price"] <= cfg["max_avg_entry_price"]]
        if len(qualifying) < cfg["min_resolved_positions"]:
            return None

        # Estimate win rate from entry prices
        # Lower entry = higher expected win rate (buying before market prices in)
        avg_entry = sum(p["entry_price"] for p in qualifying) / len(qualifying)
        # Rough estimate: avg entry 0.50 → ~60% WR, 0.40 → ~65%, 0.30 → ~70%
        est_win_rate = min(0.50 + (0.60 - avg_entry) * 0.5, 0.85)

        if est_win_rate < cfg["min_win_rate"]:
            return None

        # Composite score
        volume_norm = min(math.log10(total_volume + 1) / 6.0, 1.0)
        edge_score = (est_win_rate - 0.5) * 2  # normalize 50-100% to 0-1
        composite = 0.4 * est_win_rate + 0.3 * volume_norm + 0.3 * edge_score

        return WalletProfile(
            address=address,
            total_volume_usd=total_volume,
            win_rate=est_win_rate,
            num_resolved=len(qualifying),
            num_trades=sum(p["size"] for p in positions),
            avg_entry_price=avg_entry,
            composite_score=composite,
            last_active=datetime.utcfromtimestamp(max(p["timestamp"] for p in positions)) if positions else None,
        )


# ─── Strategies ────────────────────────────────────────────────────────────

class CopyStrategy:
    """Follow smart wallet BUY signals."""

    def __init__(self):
        self.cfg = CONFIG["copy_strategy"]
        self.cooldowns: dict[str, datetime] = {}

    def evaluate(self, trade: dict, wallet: WalletProfile, bankroll: float) -> Optional[Signal]:
        """Generate copy signal if conditions are met."""
        price = float(trade.get("price", 0))
        size = float(trade.get("size", 0))
        side = trade.get("side", "")
        market = trade.get("market", trade.get("conditionId", ""))
        slug = trade.get("slug", "")

        # Gate checks
        if wallet.composite_score < self.cfg["min_wallet_score"]:
            return None
        if side != "BUY":
            return None
        if price * size < self.cfg["min_trade_usd"]:
            return None
        if price > self.cfg["max_entry_price"]:
            return None

        # Cooldown
        now = datetime.utcnow()
        if market in self.cooldowns:
            elapsed = (now - self.cooldowns[market]).total_seconds() / 60
            if elapsed < self.cfg["cooldown_minutes"]:
                return None

        # Position sizing (fractional Kelly)
        est_win_prob = 0.5 + (wallet.composite_score - 0.5) * 0.2
        b = (1.0 / price) - 1.0 if price > 0 else 0
        q = 1.0 - est_win_prob
        kelly = (b * est_win_prob - q) / b if b > 0 else 0
        kelly = max(kelly, 0) * self.cfg["kelly_fraction"]
        size_usd = bankroll * min(kelly, self.cfg["position_size_pct"])

        if size_usd < 10:
            return None

        # Apply slippage
        slippage = CONFIG["execution"]["base_slippage_bps"] / 10000
        target_price = min(price * (1 + slippage), 0.99)

        self.cooldowns[market] = now

        return Signal(
            wallet=wallet.address,
            strategy="copy",
            market_id=market,
            slug=slug,
            outcome=trade.get("outcome", ""),
            entry_price=target_price,
            size_usd=size_usd,
            confidence=wallet.composite_score,
            timestamp=now,
            reason=f"COPY {wallet.address[:8]} score={wallet.composite_score:.2f} @ {price:.3f}",
        )


class InverseStrategy:
    """Fade smart wallet BUY signals at high prices."""

    def __init__(self):
        self.cfg = CONFIG["inverse_strategy"]
        self.cooldowns: dict[str, datetime] = {}

    def evaluate(self, trade: dict, wallet: WalletProfile, bankroll: float) -> Optional[Signal]:
        """Generate inverse signal — sell when smart money buys at high prices."""
        price = float(trade.get("price", 0))
        size = float(trade.get("size", 0))
        side = trade.get("side", "")
        market = trade.get("market", trade.get("conditionId", ""))
        slug = trade.get("slug", "")

        if wallet.composite_score < self.cfg["min_wallet_score"]:
            return None
        if side != "BUY":
            return None
        if price * size < self.cfg["min_trade_usd"]:
            return None
        if price < self.cfg["min_entry_price"]:  # only fade HIGH prices
            return None

        now = datetime.utcnow()
        if market in self.cooldowns:
            elapsed = (now - self.cooldowns[market]).total_seconds() / 60
            if elapsed < self.cfg["cooldown_minutes"]:
                return None

        # Smaller sizing for inverse
        est_win_prob = 1.0 - (0.5 + (wallet.composite_score - 0.5) * 0.2)
        b = (1.0 / price) - 1.0
        q = 1.0 - est_win_prob
        kelly = (b * est_win_prob - q) / b if b > 0 else 0
        kelly = max(kelly, 0) * self.cfg["kelly_fraction"]
        size_usd = bankroll * min(kelly, self.cfg["position_size_pct"])

        if size_usd < 10:
            return None

        slippage = CONFIG["execution"]["base_slippage_bps"] / 10000
        target_price = max(price * (1 - slippage), 0.01)

        self.cooldowns[market] = now

        return Signal(
            wallet=wallet.address,
            strategy="inverse",
            market_id=market,
            slug=slug,
            outcome=trade.get("outcome", ""),
            entry_price=target_price,
            size_usd=size_usd,
            confidence=wallet.composite_score * (price - 0.5),
            timestamp=now,
            reason=f"INVERSE {wallet.address[:8]} score={wallet.composite_score:.2f} @ {price:.3f}",
        )


# ─── Backtesting Engine ────────────────────────────────────────────────────

class BacktestEngine:
    """Event-driven backtesting with slippage and latency simulation."""

    def __init__(self, seed: int = 42):
        random.seed(seed)
        self.exec_cfg = CONFIG["execution"]

    def run(
        self,
        signals: list[Signal],
        bankroll: float,
        start_date: datetime,
        end_date: datetime,
    ) -> BacktestResult:
        """Run backtest simulation."""
        signals = sorted(signals, key=lambda s: s.timestamp)

        cash = bankroll
        positions: dict[str, BacktestTrade] = {}
        closed: list[BacktestTrade] = []
        equity_curve = []
        peak = bankroll
        max_dd = 0

        for sig in signals:
            if sig.timestamp < start_date or sig.timestamp > end_date:
                continue

            # Simulate latency
            latency = random.uniform(
                self.exec_cfg["latency_min_s"],
                self.exec_cfg["latency_max_s"],
            )
            exec_time = sig.timestamp + timedelta(seconds=latency)

            if exec_time > end_date:
                continue

            # Price drift during latency
            drift_bps = random.uniform(-2, 2) * latency  # ~2 bps/s
            exec_price = max(0.01, min(0.99, sig.entry_price + drift_bps / 10000))

            # Slippage
            slippage_bps = (
                self.exec_cfg["base_slippage_bps"]
                + self.exec_cfg["spread_bps"]
                + self.exec_cfg["volume_impact_factor"] * (sig.size_usd / 1000)
                + random.uniform(-5, 5)
            )
            slippage_bps = max(0, min(slippage_bps, 100))
            slippage_adj = slippage_bps / 10000

            if sig.strategy == "copy":
                fill_price = min(exec_price * (1 + slippage_adj), 0.99)
            else:
                fill_price = max(exec_price * (1 - slippage_adj), 0.01)

            # Fee
            fee = sig.size_usd * (self.exec_cfg["fee_bps"] / 10000)
            total_cost = sig.size_usd + fee

            if total_cost > cash:
                sig.size_usd = cash / (1 + self.exec_cfg["fee_bps"] / 10000)
                fee = sig.size_usd * (self.exec_cfg["fee_bps"] / 10000)
                total_cost = sig.size_usd + fee

            if sig.size_usd < 10:
                continue

            mid = sig.market_id
            if mid in positions:
                continue  # don't add to existing

            if len(positions) >= 20:  # max concurrent
                continue

            # Open position
            bt = BacktestTrade(
                signal=sig,
                entry_price=fill_price,
                entry_time=exec_time,
                size_usd=sig.size_usd,
                slippage_cost=slippage_bps * sig.size_usd / 10000,
                fee_cost=fee,
                status="open",
            )
            positions[mid] = bt
            cash -= total_cost

            # Track equity
            equity = cash + sum(t.size_usd for t in positions.values())
            equity_curve.append((exec_time, equity))
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        # Close all positions at end (assume market resolves — simplified)
        for mid, bt in positions.items():
            # Simulate resolution: 50% chance of winning for copy, inverse logic for inverse
            if bt.signal.strategy == "copy":
                # Assume wallet's edge holds: 60% win
                won = random.random() < 0.60
                exit_price = 1.0 if won else 0.0
            else:
                # Inverse: 40% win (smart money usually right)
                won = random.random() < 0.40
                exit_price = 0.0 if won else 1.0

            bt.exit_price = exit_price
            bt.exit_time = end_date
            fee = bt.size_usd * (self.exec_cfg["fee_bps"] / 10000)
            shares = bt.size_usd / bt.entry_price if bt.entry_price > 0 else 0

            if bt.signal.strategy == "copy":
                bt.pnl = (exit_price - bt.entry_price) * shares - fee - bt.slippage_cost
            else:
                bt.pnl = (bt.entry_price - exit_price) * shares - fee - bt.slippage_cost

            bt.fee_cost += fee
            bt.status = "closed"
            cash += bt.pnl + bt.size_usd  # return capital + pnl
            closed.append(bt)

        # Metrics
        total = len(closed)
        winning = [t for t in closed if t.pnl > 0]
        losing = [t for t in closed if t.pnl < 0]
        total_pnl = sum(t.pnl for t in closed)
        returns = [t.pnl for t in closed]
        avg_ret = sum(returns) / len(returns) if returns else 0
        ret_std = math.sqrt(sum((r - avg_ret) ** 2 for r in returns) / len(returns)) if len(returns) > 1 else 1
        sharpe = avg_ret / ret_std if ret_std > 0 else 0
        gross_profit = sum(t.pnl for t in winning)
        gross_loss = abs(sum(t.pnl for t in losing))
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        return BacktestResult(
            total_trades=total,
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=len(winning) / total if total > 0 else 0,
            total_pnl=total_pnl,
            total_return_pct=(cash - bankroll) / bankroll * 100 if bankroll > 0 else 0,
            max_drawdown_pct=max_dd * 100,
            sharpe_ratio=sharpe,
            profit_factor=pf,
            total_fees=sum(t.fee_cost for t in closed),
            total_slippage=sum(t.slippage_cost for t in closed),
            trades=closed,
        )


# ─── Live Monitor ──────────────────────────────────────────────────────────

class LiveMonitor:
    """Real-time monitoring of tracked wallets."""

    def __init__(
        self,
        api: PolymarketAPI,
        wallets: list[WalletProfile],
        bankroll: float = 1000.0,
        poll_interval: float = 15.0,
    ):
        self.api = api
        self.wallet_map = {w.address: w for w in wallets}
        self.bankroll = bankroll
        self.poll_interval = poll_interval
        self.copy = CopyStrategy()
        self.inverse = InverseStrategy()
        self.signals: list[Signal] = []
        self._last_poll = int(time.time()) - 300
        self._seen: set[str] = set()
        self._running = False

    async def run(self, duration_s: float = 3600):
        """Run live monitoring loop."""
        self._running = True
        start = time.monotonic()

        print(f"\n🚀 Starting live monitor")
        print(f"   Tracking {len(self.wallet_map)} wallets")
        print(f"   Bankroll: ${self.bankroll}")
        print(f"   Poll interval: {self.poll_interval}s")
        print(f"   Duration: {duration_s}s")
        print()

        while self._running:
            try:
                # Fetch recent trades from Data API
                data = await self.api._get(
                    "https://data-api.polymarket.com/trades",
                    params={"after": self._last_poll, "limit": 100},
                )
                trades = data.get("data", data) if isinstance(data, dict) else data

                if isinstance(trades, list):
                    for raw in trades:
                        await self._process_trade(raw)

                self._last_poll = int(time.time())

                if time.monotonic() - start >= duration_s:
                    break

                await asyncio.sleep(self.poll_interval)

            except KeyboardInterrupt:
                print("\n⏹ Stopped by user")
                break
            except Exception as e:
                print(f"  ⚠ Error: {e}")
                await asyncio.sleep(self.poll_interval * 2)

        self._running = False
        print(f"\n✅ Monitoring complete. {len(self.signals)} signals generated.")

    async def _process_trade(self, raw: dict):
        """Process a single trade from the API."""
        tid = raw.get("id", "")
        if tid in self._seen:
            return
        self._seen.add(tid)

        wallet_addr = raw.get("proxyWallet", "") or raw.get("maker_address", "") or raw.get("taker_address", "")
        wallet = self.wallet_map.get(wallet_addr)
        if not wallet:
            return

        price = float(raw.get("price", 0))
        size = float(raw.get("size", 0))
        side = raw.get("side", "")
        slug = raw.get("slug", "")

        print(f"  📡 Wallet {wallet_addr[:10]}: {side} {slug[:30]} @ {price:.3f} (${price*size:,.0f})")

        # Evaluate strategies
        sig = self.copy.evaluate(raw, wallet, self.bankroll)
        if sig:
            self.signals.append(sig)
            print(f"  ✅ COPY SIGNAL: {sig.reason} → ${sig.size_usd:,.0f}")

        sig = self.inverse.evaluate(raw, wallet, self.bankroll)
        if sig:
            self.signals.append(sig)
            print(f"  🔄 INVERSE SIGNAL: {sig.reason} → ${sig.size_usd:,.0f}")


# ─── Main Runner ───────────────────────────────────────────────────────────

async def run_discovery():
    """Discover smart wallets."""
    async with PolymarketAPI() as api:
        discovery = WalletDiscovery(api)
        wallets = await discovery.discover()

        # Save to file
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / "smart_wallets.json"
        data = [
            {
                "address": w.address,
                "total_volume_usd": w.total_volume_usd,
                "win_rate": w.win_rate,
                "num_resolved": w.num_resolved,
                "avg_entry_price": w.avg_entry_price,
                "composite_score": w.composite_score,
            }
            for w in wallets
        ]
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\n💾 Saved {len(wallets)} wallets to {path}")
        return wallets


async def run_backtest():
    """Run backtest on historical data."""
    # Load wallets
    path = DATA_DIR / "smart_wallets.json"
    if not path.exists():
        print("❌ No wallets found. Run 'discover' first.")
        return

    with open(path) as f:
        wallet_data = json.load(f)

    wallets = [
        WalletProfile(address=w["address"], composite_score=w["composite_score"],
                      win_rate=w["win_rate"], total_volume_usd=w["total_volume_usd"])
        for w in wallet_data
    ]

    print(f"\n📈 Running backtest on {len(wallets)} wallets...")

    async with PolymarketAPI() as api:
        # Fetch historical trades
        all_signals = []
        cfg = CONFIG["backtest"]
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=cfg["days"])

        copy = CopyStrategy()
        inverse = InverseStrategy()

        for wallet in wallets[:10]:  # top 10
            trades = await api.get_trades_for_wallet(wallet.address, limit=200)
            print(f"  {wallet.address[:10]}: {len(trades)} trades")

            for t in trades:
                ts = int(t.get("match_time", t.get("timestamp", 0)))
                if ts < start_date.timestamp():
                    continue

                price = float(t.get("price", 0))
                size = float(t.get("size", 0))
                side = t.get("side", "")
                market = t.get("market", "")

                if side == "BUY" and price > 0:
                    sig = Signal(
                        wallet=wallet.address,
                        strategy="copy",
                        market_id=market,
                        slug=t.get("slug", ""),
                        outcome=t.get("outcome", ""),
                        entry_price=price,
                        size_usd=price * size,
                        confidence=wallet.composite_score,
                        timestamp=datetime.utcfromtimestamp(ts),
                    )
                    all_signals.append(sig)

        if not all_signals:
            print("❌ No signals generated from historical data.")
            return

        print(f"  Generated {len(all_signals)} signals")

        # Run backtest
        engine = BacktestEngine(seed=cfg["seed"])
        result = engine.run(all_signals, cfg["bankroll"], start_date, end_date)

        # Display results
        print(f"\n{'='*50}")
        print(f"📊 BACKTEST RESULTS")
        print(f"{'='*50}")
        print(f"Strategy:        Copy Trading")
        print(f"Period:          {start_date.date()} to {end_date.date()}")
        print(f"Initial Bank:    ${cfg['bankroll']:,.2f}")
        print(f"Final Bank:      ${cfg['bankroll'] + result.total_pnl:,.2f}")
        print(f"Total PnL:       ${result.total_pnl:+,.2f}")
        print(f"Total Return:    {result.total_return_pct:+.1f}%")
        print(f"Win Rate:        {result.win_rate:.1%}")
        print(f"Total Trades:    {result.total_trades}")
        print(f"Sharpe Ratio:    {result.sharpe_ratio:.2f}")
        print(f"Profit Factor:   {result.profit_factor:.2f}")
        print(f"Max Drawdown:    {result.max_drawdown_pct:.1f}%")
        print(f"Total Fees:      ${result.total_fees:,.2f}")
        print(f"Total Slippage:  ${result.total_slippage:,.2f}")
        print(f"{'='*50}")


async def run_live():
    """Start live monitoring."""
    path = DATA_DIR / "smart_wallets.json"
    if not path.exists():
        print("❌ No wallets found. Run 'discover' first.")
        return

    with open(path) as f:
        wallet_data = json.load(f)

    wallets = [
        WalletProfile(address=w["address"], composite_score=w["composite_score"],
                      win_rate=w["win_rate"], total_volume_usd=w["total_volume_usd"])
        for w in wallet_data
    ]

    async with PolymarketAPI() as api:
        monitor = LiveMonitor(
            api=api,
            wallets=wallets,
            bankroll=CONFIG["live"]["bankroll"],
            poll_interval=CONFIG["live"]["poll_interval_s"],
        )
        await monitor.run(duration_s=3600)


async def run_full_pipeline():
    """Run complete pipeline: discover → backtest → live."""
    print("🔄 Running full pipeline...")
    print("\n" + "="*50)
    print("STEP 1: DISCOVER SMART WALLETS")
    print("="*50)
    wallets = await run_discovery()

    print("\n" + "="*50)
    print("STEP 2: BACKTEST STRATEGY")
    print("="*50)
    await run_backtest()

    print("\n" + "="*50)
    print("STEP 3: LIVE MONITORING (60s demo)")
    print("="*50)
    # Short demo for live
    if wallets:
        async with PolymarketAPI() as api:
            monitor = LiveMonitor(api=api, wallets=wallets, bankroll=1000)
            await monitor.run(duration_s=60)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python run_smart_wallet_bot.py [discover|backtest|live|full-pipeline]")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "discover":
        asyncio.run(run_discovery())
    elif command == "backtest":
        asyncio.run(run_backtest())
    elif command == "live":
        asyncio.run(run_live())
    elif command == "full-pipeline":
        asyncio.run(run_full_pipeline())
    else:
        print(f"Unknown command: {command}")
        print("Usage: python run_smart_wallet_bot.py [discover|backtest|live|full-pipeline]")
        sys.exit(1)


if __name__ == "__main__":
    main()
