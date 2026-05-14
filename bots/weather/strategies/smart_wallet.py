"""Smart Wallet Copy Strategy — Follow profitable weather market traders.

Instead of building our own model, we copy-trade the best weather traders.
This avoids the calibration problem entirely.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import structlog

from pm_bot.core.kelly import kelly_size
from pm_bot.core.smart_wallet import SmartWalletSignal, WalletTracker
from pm_bot.models.market import (
    ForecastResult,
    Recommendation,
    TemperatureBucket,
    WeatherEvent,
)

log = structlog.get_logger()


@dataclass
class SmartWalletStrategy:
    """Copy-trade profitable weather market wallets.

    Strategy:
    1. Track top weather traders (ColdMath, gopfan2, etc.)
    2. When they buy, we buy with delay
    3. Use confidence-based position sizing
    4. Apply risk management filters

    This avoids the model calibration problem by leveraging
    traders who have already proven profitable.
    """

    name: str = "smart_wallet"
    description: str = "Copy-trade profitable weather market wallets"

    # Sizing
    kelly_fraction: float = 0.15  # Quarter Kelly (conservative)
    max_position_usd: float = 5.0
    min_notional: float = 1.0
    max_single_pct: float = 0.03  # 3% of bankroll per position

    # Filters
    min_confidence: float = 0.5  # Minimum signal confidence
    min_wallet_pnl: float = 50_000  # Only follow wallets with $50K+ P&L
    max_trade_age_min: float = 30.0  # Only copy trades < 30min old
    min_trade_size: float = 5.0  # Ignore tiny trades

    # Price filters (based on backtest analysis)
    min_price: float = 0.30  # Don't copy tail buys (<$0.30)
    max_price: float = 0.70  # Don't copy high-price trades (>$0.70)
    max_slippage: float = 0.05  # 5% max slippage

    # Risk
    max_positions_per_wallet: int = 3  # Max positions from same wallet
    cooldown_min: float = 30.0  # Don't re-enter same market within 30min

    def run(
        self,
        event: WeatherEvent,
        forecast: ForecastResult,
        bankroll: float = 100.0,
        **kwargs,
    ) -> list[Recommendation]:
        """Generate recommendations based on smart wallet signals.

        This strategy doesn't use the forecast model at all.
        It only acts on signals from tracked wallets.

        Note: This strategy is meant to be used with the WalletTracker
        which provides the actual signals. The event/forecast params
        are kept for interface compatibility.
        """
        # Get signals from kwargs (passed by daemon)
        signals: list[SmartWalletSignal] = kwargs.get("wallet_signals", [])
        if not signals:
            return []

        recs: list[Recommendation] = []

        for signal in signals:
            # Filter by confidence
            if signal.confidence < self.min_confidence:
                continue

            # Filter by price (key insight from backtest)
            price = signal.trade.price
            if price < self.min_price:
                log.debug("skip_tail_buy", price=price, min=self.min_price)
                continue
            if price > self.max_price:
                log.debug("skip_high_price", price=price, max=self.max_price)
                continue

            # Filter by wallet P&L
            # (This is already filtered in WalletTracker, but double-check)

            # Find matching bucket in event
            bucket = self._find_matching_bucket(event, signal)
            if bucket is None:
                continue

            # Determine direction
            if signal.trade.side == "BUY":
                direction = "YES"
            else:
                # For sells, we could buy NO or skip
                # For now, skip sells (could be profit-taking)
                continue

            # Apply slippage
            actual_price = price * (1 + self.max_slippage)
            if actual_price > 0.99:
                actual_price = 0.99

            # Compute position size
            size = self._compute_size(signal, actual_price, bankroll)
            if size is None:
                continue

            # Compute edge (estimated, not model-based)
            # Higher confidence = higher assumed edge
            edge = signal.confidence * 0.15  # Max 15% edge estimate

            rec = Recommendation(
                bucket=bucket,
                direction=direction,
                price=actual_price,
                edge=edge,
                size_usd=size,
                strategy=self.name,
                reason=signal.reason,
            )
            recs.append(rec)

            log.info(
                "smart_wallet_rec",
                wallet=signal.wallet_name,
                direction=direction,
                price=actual_price,
                raw_price=price,
                size=size,
                confidence=signal.confidence,
            )

        return recs

    def _find_matching_bucket(
        self, event: WeatherEvent, signal: SmartWalletSignal
    ) -> TemperatureBucket | None:
        """Find the bucket that matches the signal's trade."""
        # Try to match by market_id or token_id
        for bucket in event.buckets:
            if bucket.market_id == signal.trade.market_id:
                return bucket
            # Could also match by token_id if available

        # If no exact match, try fuzzy matching
        # (This would require parsing the bucket question)
        return None

    def _compute_size(
        self,
        signal: SmartWalletSignal,
        price: float,
        bankroll: float,
    ) -> float | None:
        """Compute position size based on signal confidence."""
        if price <= 0 or price >= 1:
            return None

        # Base size from Kelly
        # Use signal confidence as edge proxy
        edge = signal.confidence * 0.15
        kelly = kelly_size(edge, price)

        # Apply Kelly fraction
        kelly *= self.kelly_fraction

        # Apply position limits
        size = bankroll * kelly
        size = min(size, self.max_position_usd)
        size = min(size, bankroll * self.max_single_pct)

        if size < self.min_notional:
            return None

        return round(size, 2)


@dataclass
class AdaptiveSmartWalletStrategy:
    """Adaptive version that adjusts sizing based on wallet performance.

    Tracks which wallets are currently hot (recent P&L) and
    increases allocation to better-performing wallets.
    """

    name: str = "adaptive_smart_wallet"
    description: str = "Adaptive copy-trading with dynamic sizing"

    # Base sizing
    kelly_fraction: float = 0.15
    max_position_usd: float = 10.0
    min_notional: float = 1.0
    max_single_pct: float = 0.05

    # Filters
    min_confidence: float = 0.4
    min_wallet_pnl: float = 20_000  # Lower bar for adaptive
    max_trade_age_min: float = 45.0
    min_trade_size: float = 2.0

    # Price filters (same as base strategy)
    min_price: float = 0.30
    max_price: float = 0.70
    max_slippage: float = 0.05

    # Adaptive parameters
    hot_wallet_boost: float = 1.5  # 50% more for hot wallets
    cold_wallet_reduce: float = 0.5  # 50% less for cold wallets

    def run(
        self,
        event: WeatherEvent,
        forecast: ForecastResult,
        bankroll: float = 100.0,
        **kwargs,
    ) -> list[Recommendation]:
        """Generate recommendations with adaptive sizing."""
        signals: list[SmartWalletSignal] = kwargs.get("wallet_signals", [])
        if not signals:
            return []

        # Group signals by wallet
        wallet_signals: dict[str, list[SmartWalletSignal]] = {}
        for sig in signals:
            wallet = sig.wallet_name
            if wallet not in wallet_signals:
                wallet_signals[wallet] = []
            wallet_signals[wallet].append(sig)

        recs: list[Recommendation] = []

        for wallet, wallet_sigs in wallet_signals.items():
            # Compute wallet performance multiplier
            perf_mult = self._get_performance_multiplier(wallet)

            for signal in wallet_sigs:
                if signal.confidence < self.min_confidence:
                    continue

                # Price filters (based on backtest analysis)
                price = signal.trade.price
                if price < self.min_price:
                    continue
                if price > self.max_price:
                    continue

                bucket = self._find_matching_bucket(event, signal)
                if bucket is None:
                    continue

                if signal.trade.side != "BUY":
                    continue

                # Apply slippage
                actual_price = price * (1 + self.max_slippage)
                if actual_price > 0.99:
                    actual_price = 0.99

                size = self._compute_adaptive_size(
                    signal, actual_price, bankroll, perf_mult
                )
                if size is None:
                    continue

                edge = signal.confidence * 0.15 * perf_mult

                rec = Recommendation(
                    bucket=bucket,
                    direction="YES",
                    price=actual_price,
                    edge=edge,
                    size_usd=size,
                    strategy=self.name,
                    reason=f"{signal.reason} (perf_mult={perf_mult:.1f})",
                )
                recs.append(rec)

        return recs

    def _get_performance_multiplier(self, wallet: str) -> float:
        """Get performance multiplier for a wallet.

        Returns > 1.0 for hot wallets, < 1.0 for cold wallets.
        """
        # This would track recent P&L per wallet
        # For now, return 1.0 (no adjustment)
        return 1.0

    def _find_matching_bucket(
        self, event: WeatherEvent, signal: SmartWalletSignal
    ) -> TemperatureBucket | None:
        """Find matching bucket."""
        for bucket in event.buckets:
            if bucket.market_id == signal.trade.market_id:
                return bucket
        return None

    def _compute_adaptive_size(
        self,
        signal: SmartWalletSignal,
        price: float,
        bankroll: float,
        perf_mult: float,
    ) -> float | None:
        """Compute size with performance adjustment."""
        if price <= 0 or price >= 1:
            return None

        edge = signal.confidence * 0.15
        kelly = kelly_size(edge, price)
        kelly *= self.kelly_fraction
        kelly *= perf_mult  # Adjust by wallet performance

        size = bankroll * kelly
        size = min(size, self.max_position_usd)
        size = min(size, bankroll * self.max_single_pct)

        if size < self.min_notional:
            return None

        return round(size, 2)
