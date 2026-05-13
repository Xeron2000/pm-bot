"""Copy-trading and inverse smart wallet strategies.

Strategy logic:
- COPY: When a high-confidence smart wallet buys, we buy at the same price or slightly better.
- INVERSE: When a high-confidence smart wallet buys, we sell (bet against them).

Each strategy includes:
- Position sizing (Kelly-fraction or fixed % of bankroll)
- Entry/exit rules with price tolerance
- Slippage and fee awareness
- Cooldown periods to avoid chasing

Reference:
- Polymarket fee structure: https://docs.polymarket.com/trading/fees
- CLOB order types: https://docs.polymarket.com/trading/orders
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta
from typing import Optional

import structlog

from pm_bot.smart_wallet.models import (
    BacktestTrade,
    CopySignal,
    Side,
    StrategyType,
    Trade,
    WalletProfile,
)

logger = structlog.get_logger(__name__)

# Default strategy parameters — Small Capital Optimized
# Based on Polyloly research: 334 trades, +46.7% ROI at zero slippage
# Realistic ROI after costs: +15-25% annually
# Key filters: score ≥0.6, entry price ≤$0.65, min $5 trade size
DEFAULT_PARAMS = {
    "min_wallet_score": 0.6,           # minimum composite_score to follow
    "min_trade_usd": 5.0,              # minimum trade size to trigger signal (reduced for small capital)
    "max_entry_price_copy": 0.65,      # don't buy above 65c — alpha disappears above this (Polyloly data)
    "min_entry_price_inverse": 0.60,   # only fade at high prices (raised from 0.20)
    "position_size_pct": 0.02,         # 2% of bankroll per trade
    "max_position_pct": 0.05,          # 5% max in single market
    "max_position_usd": 10.0,          # $10 max per position (small capital cap)
    "max_concurrent_positions": 20,    # max open positions
    "cooldown_minutes": 30,            # min time between trades on same market
    "slippage_bps": 20,                # assumed slippage in basis points
    "fee_bps": 30,                     # Polymarket taker fee (0.30%)
    "latency_seconds": 5.0,            # assumed execution latency
    "kelly_fraction": 0.25,            # quarter-Kelly for conservative sizing
    "stop_loss_pct": 0.30,             # stop if position drops 30%
    "take_profit_pct": 0.50,           # take profit at 50% gain
}


class CopyStrategy:
    """Follow smart wallet trades — Small Capital Optimized.

    Based on Polyloly research:
    - 334 trades, 75.9% win rate, +46.7% ROI (zero slippage)
    - Realistic ROI after costs: +15-25% annually
    - Key filters: score ≥0.6, entry price ≤$0.65
    - Quarter Kelly for conservative sizing

    Signal generation:
    1. Monitor real-time trades from tracked wallets
    2. Filter by wallet score, trade size, and price
    3. Generate BUY signal at current price + slippage
    4. Size position using Kelly fraction or fixed %
    5. Cap at $10 per position for small capital
    """

    def __init__(self, params: Optional[dict] = None):
        self.params = {**DEFAULT_PARAMS, **(params or {})}
        self._cooldowns: dict[str, datetime] = {}  # market_id -> last trade time
        self._positions: dict[str, float] = {}      # market_id -> avg_entry_price

    def evaluate(
        self,
        trade: Trade,
        wallet: WalletProfile,
        bankroll: float,
    ) -> Optional[CopySignal]:
        """Evaluate whether to copy a smart wallet trade.

        Args:
            trade: The observed smart wallet trade.
            wallet: The wallet's profile/score.
            bankroll: Current available bankroll.

        Returns:
            CopySignal if conditions are met, None otherwise.
        """
        # Gate checks
        if wallet.composite_score < self.params["min_wallet_score"]:
            return None
        if trade.size_usd < self.params["min_trade_usd"]:
            return None
        if trade.side == Side.SELL:
            return None  # only copy buys (selling is ambiguous — could be taking profit)

        mid = trade.market_id
        now = datetime.utcnow()

        # Cooldown check
        if mid in self._cooldowns:
            elapsed = (now - self._cooldowns[mid]).total_seconds() / 60
            if elapsed < self.params["cooldown_minutes"]:
                logger.debug("cooldown_active", market=mid[:8])
                return None

        # Price gate — don't buy at extreme prices
        if trade.price > self.params["max_entry_price_copy"]:
            logger.debug("price_too_high", price=trade.price, market=mid[:8])
            return None

        # Position sizing
        target_size = self._calculate_size(
            price=trade.price,
            wallet_score=wallet.composite_score,
            bankroll=bankroll,
        )

        if target_size < 5.0:  # minimum $5 position (small capital)
            return None

        # Calculate target entry price with slippage
        slippage = self.params["slippage_bps"] / 10000
        target_price = min(trade.price * (1 + slippage), 0.99)

        # Generate signal
        signal = CopySignal(
            wallet=wallet,
            trade=trade,
            strategy=StrategyType.COPY,
            confidence=wallet.composite_score * (1 - (trade.price - 0.5) ** 2),
            target_price=target_price,
            target_size_usd=target_size,
            reason=f"COPY wallet {wallet.address[:8]} score={wallet.composite_score:.2f} "
                   f"outcome={trade.outcome} @ {trade.price:.3f}",
            timestamp=now,
        )

        # Update cooldown
        self._cooldowns[mid] = now
        self._positions[mid] = target_price

        return signal

    def _calculate_size(self, price: float, wallet_score: float, bankroll: float) -> float:
        """Position sizing using fractional Kelly criterion.

        Kelly: f = (bp - q) / b
        where b = odds, p = win prob, q = 1-p

        For binary outcomes at price P:
        - b = (1/P - 1)  [potential payout per dollar risked]
        - p = estimated win probability (from wallet score)
        - Fractional Kelly: use kelly_fraction of full Kelly
        """
        # Estimate win probability from wallet score
        # A score of 1.0 implies ~60% edge, score of 0.5 implies ~50% (no edge)
        est_win_prob = 0.5 + (wallet_score - 0.5) * 0.20  # maps [0.5, 1.0] -> [0.50, 0.60]

        # Kelly fraction
        b = (1.0 / price) - 1.0 if price > 0 else 0
        if b <= 0:
            return 0.0
        q = 1.0 - est_win_prob
        kelly = (b * est_win_prob - q) / b
        kelly = max(kelly, 0)

        # Apply fractional Kelly and caps
        fraction = kelly * self.params["kelly_fraction"]
        fraction = min(fraction, self.params["position_size_pct"])
        fraction = min(fraction, self.params["max_position_pct"])

        size_usd = bankroll * fraction
        # Cap at max_position_usd for small capital
        size_usd = min(size_usd, self.params.get("max_position_usd", 10.0))
        return size_usd

    def should_exit(
        self,
        market_id: str,
        entry_price: float,
        current_price: float,
    ) -> tuple[bool, str]:
        """Check if position should be exited.

        Returns (should_exit, reason).
        """
        if entry_price <= 0:
            return False, ""

        pnl_pct = (current_price - entry_price) / entry_price

        # Stop loss
        if pnl_pct <= -self.params["stop_loss_pct"]:
            return True, f"stop_loss ({pnl_pct:.1%})"

        # Take profit
        if pnl_pct >= self.params["take_profit_pct"]:
            return True, f"take_profit ({pnl_pct:.1%})"

        return False, ""


class InverseStrategy:
    """Trade against smart wallet trades.

    Logic: When a smart wallet buys YES at high price, we sell YES (or buy NO).
    Rationale: If smart money is buying at 80c, the market is already efficient,
    and the edge is gone. Better to fade late entries.

    NOTE: Inverse has weaker evidence than Copy. Use tighter filters.
    Multiple sources suggest Copy is significantly better than Inverse.
    """

    def __init__(self, params: Optional[dict] = None):
        # Inverse strategy has weaker evidence than Copy.
        # Use tighter filters and smaller position sizes.
        inverse_defaults = {
            "min_entry_price_inverse": 0.70,   # only fade at 70c+ (raised from 0.60)
            "min_wallet_score": 0.7,            # need higher score to trust inverse
            "min_trade_usd": 100.0,             # need higher conviction
            "position_size_pct": 0.01,          # 1% per trade (half of Copy)
            "max_position_pct": 0.03,           # 3% max (half of Copy)
            "max_position_usd": 5.0,            # $5 max (smaller than Copy)
        }
        self.params = {**DEFAULT_PARAMS, **inverse_defaults, **(params or {})}
        self._cooldowns: dict[str, datetime] = {}

    def evaluate(
        self,
        trade: Trade,
        wallet: WalletProfile,
        bankroll: float,
    ) -> Optional[CopySignal]:
        """Evaluate whether to trade against a smart wallet.

        Inverse only triggers when:
        1. Wallet score is high (we only fade confident traders)
        2. Trade is a BUY at elevated price (>0.60)
        3. We sell at the same price (provide liquidity)
        """
        if wallet.composite_score < self.params["min_wallet_score"]:
            return None
        if trade.size_usd < self.params["min_trade_usd"]:
            return None
        if trade.side == Side.SELL:
            return None  # don't inverse sells

        mid = trade.market_id
        now = datetime.utcnow()

        # Cooldown
        if mid in self._cooldowns:
            elapsed = (now - self._cooldowns[mid]).total_seconds() / 60
            if elapsed < self.params["cooldown_minutes"]:
                return None

        # Inverse price gate — only fade at HIGH prices (market already agrees with smart money)
        if trade.price < self.params["min_entry_price_inverse"]:
            return None

        # At very high prices, the smart money is late and we should fade
        # The higher the price, the stronger the inverse signal
        confidence = wallet.composite_score * (trade.price - 0.5)  # stronger at extremes

        # Position sizing (smaller for inverse — it's contrarian)
        est_win_prob = 1.0 - (0.5 + (wallet.composite_score - 0.5) * 0.20)
        b = (1.0 / trade.price) - 1.0
        q = 1.0 - est_win_prob
        kelly = (b * est_win_prob - q) / b if b > 0 else 0
        kelly = max(kelly, 0) * self.params["kelly_fraction"] * 0.5  # half size for inverse
        size_usd = bankroll * min(kelly, self.params["position_size_pct"])

        if size_usd < 10.0:
            return None

        slippage = self.params["slippage_bps"] / 10000
        target_price = max(trade.price * (1 - slippage), 0.01)

        signal = CopySignal(
            wallet=wallet,
            trade=trade,
            strategy=StrategyType.INVERSE,
            confidence=min(confidence, 0.8),
            target_price=target_price,
            target_size_usd=size_usd,
            reason=f"INVERSE wallet {wallet.address[:8]} score={wallet.composite_score:.2f} "
                   f"outcome={trade.outcome} @ {trade.price:.3f} (high price fade)",
            timestamp=now,
        )

        self._cooldowns[mid] = now
        return signal

    def should_exit(
        self,
        market_id: str,
        entry_price: float,
        current_price: float,
    ) -> tuple[bool, str]:
        """Exit logic for inverse positions."""
        if entry_price <= 0:
            return False, ""

        # For inverse (we sold), profit when price drops
        pnl_pct = (entry_price - current_price) / entry_price

        if pnl_pct <= -self.params["stop_loss_pct"]:
            return True, f"stop_loss ({pnl_pct:.1%})"
        if pnl_pct >= self.params["take_profit_pct"]:
            return True, f"take_profit ({pnl_pct:.1%})"

        return False, ""
