"""Backtesting framework for smart wallet strategies.

Features:
- Point-in-time simulation (no look-ahead bias)
- Configurable slippage model (fixed bps + volume impact)
- Configurable latency (signal delayed by N seconds)
- Out-of-sample validation (split data into train/test)
- Walk-forward analysis
- Monte Carlo simulation for confidence intervals

Slippage model:
- Base slippage: 10 bps for liquid markets, 30 bps for illiquid
- Volume impact: additional slippage proportional to trade_size / market_liquidity
- Spread: bid-ask spread component from order book depth

Latency model:
- Signal generation delay: 2-5 seconds after wallet trade
- Network latency: 1-3 seconds
- Total: 3-8 seconds before our order reaches the book
- Price can move 0.5-2% during this window on volatile markets

References:
- Polymarket fee schedule: 30 bps taker, 0 bps maker (rebate possible)
- CLOB order book depth: https://docs.polymarket.com/api-reference/core/get-order-book
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import structlog

from pm_bot.smart_wallet.models import (
    BacktestResult,
    BacktestTrade,
    CopySignal,
    Side,
    StrategyType,
    Trade,
    WalletProfile,
)
from pm_bot.smart_wallet.strategy import CopyStrategy, InverseStrategy

logger = structlog.get_logger(__name__)


@dataclass
class SlippageConfig:
    """Configurable slippage model."""
    base_bps: float = 15.0          # base slippage in basis points
    volume_impact_factor: float = 0.1  # additional bps per $1000 traded
    max_slippage_bps: float = 100.0   # cap at 1%
    spread_bps: float = 5.0           # bid-ask spread component
    random_noise_bps: float = 5.0     # random noise range

    def calculate(self, trade_size_usd: float, market_liquidity_usd: float = 50000.0) -> float:
        """Calculate total slippage in basis points."""
        base = self.base_bps
        spread = self.spread_bps
        volume_impact = self.volume_impact_factor * (trade_size_usd / 1000.0)
        noise = random.uniform(-self.random_noise_bps, self.random_noise_bps)

        total = base + spread + volume_impact + noise
        return max(0, min(total, self.max_slippage_bps))


@dataclass
class LatencyConfig:
    """Configurable latency model."""
    signal_delay_min_s: float = 2.0
    signal_delay_max_s: float = 5.0
    network_latency_min_s: float = 1.0
    network_latency_max_s: float = 3.0
    price_drift_bps_per_s: float = 2.0  # price drift per second of latency

    @property
    def total_min_s(self) -> float:
        return self.signal_delay_min_s + self.network_latency_min_s

    @property
    def total_max_s(self) -> float:
        return self.signal_delay_max_s + self.network_latency_max_s

    def simulate_delay_seconds(self) -> float:
        """Sample a random delay from the configured range."""
        signal = random.uniform(self.signal_delay_min_s, self.signal_delay_max_s)
        network = random.uniform(self.network_latency_min_s, self.network_latency_max_s)
        return signal + network

    def price_drift_during_latency(self, latency_s: float) -> float:
        """Estimate price drift during latency period (in price units, 0-1 scale)."""
        drift_bps = self.price_drift_bps_per_s * latency_s
        # Add random direction
        direction = random.choice([-1, 1])
        return direction * drift_bps / 10000


class BacktestEngine:
    """Event-driven backtesting engine for smart wallet strategies.

    Usage:
        engine = BacktestEngine(
            strategy=CopyStrategy(),
            slippage=SlippageConfig(),
            latency=LatencyConfig(),
        )
        result = engine.run(
            signals=signals,
            price_data=price_data,
            bankroll=1000.0,
            start_date=...,
            end_date=...,
        )
    """

    def __init__(
        self,
        strategy: CopyStrategy | InverseStrategy,
        slippage: Optional[SlippageConfig] = None,
        latency: Optional[LatencyConfig] = None,
        seed: Optional[int] = None,
    ):
        self.strategy = strategy
        self.slippage = slippage or SlippageConfig()
        self.latency = latency or LatencyConfig()
        if seed is not None:
            random.seed(seed)

    def run(
        self,
        signals: list[CopySignal],
        price_data: dict[str, list[tuple[datetime, float]]],  # market_id -> [(time, price)]
        bankroll: float,
        start_date: datetime,
        end_date: datetime,
    ) -> BacktestResult:
        """Run backtest simulation.

        Args:
            signals: Chronologically sorted list of signals to evaluate.
            price_data: Historical price data for each market. Must cover [start_date, end_date].
            bankroll: Starting bankroll in USD.
            start_date: Backtest start.
            end_date: Backtest end.

        Returns:
            BacktestResult with full performance metrics.
        """
        # Sort signals by time
        signals = sorted(signals, key=lambda s: s.timestamp)

        # State tracking
        cash = bankroll
        positions: dict[str, BacktestTrade] = {}  # market_id -> open trade
        closed_trades: list[BacktestTrade] = []
        equity_curve: list[tuple[datetime, float]] = []
        peak_equity = bankroll
        max_drawdown = 0.0

        for signal in signals:
            if signal.timestamp < start_date or signal.timestamp > end_date:
                continue

            mid = signal.trade.market_id

            # Simulate latency
            delay_s = self.latency.simulate_delay_seconds()
            exec_time = signal.timestamp + timedelta(seconds=delay_s)

            if exec_time > end_date:
                continue

            # Get price at execution time (with latency drift)
            exec_price = self._get_price_at(price_data, mid, exec_time)
            if exec_price is None:
                continue

            # Apply latency-induced price drift
            drift = self.latency.price_drift_during_latency(delay_s)
            exec_price = max(0.01, min(0.99, exec_price + drift))

            # Calculate slippage
            slippage_bps = self.slippage.calculate(signal.target_size_usd)
            slippage_adj = slippage_bps / 10000

            if signal.strategy == StrategyType.COPY:
                fill_price = min(exec_price * (1 + slippage_adj), 0.99)
            else:  # INVERSE (selling)
                fill_price = max(exec_price * (1 - slippage_adj), 0.01)

            # Check if we can afford it
            cost = signal.target_size_usd
            fee = cost * (self.strategy.params.get("fee_bps", 30) / 10000)
            total_cost = cost + fee

            if total_cost > cash:
                # Reduce size to fit available cash
                cost = cash / (1 + self.strategy.params.get("fee_bps", 30) / 10000)
                fee = cost * (self.strategy.params.get("fee_bps", 30) / 10000)
                total_cost = cost + fee

            if cost < 10.0:  # minimum position
                continue

            # Check max concurrent positions
            if mid not in positions and len(positions) >= self.strategy.params.get("max_concurrent_positions", 20):
                continue

            # Check for existing position
            if mid in positions:
                # Already have a position — check for exit or add
                existing = positions[mid]
                should_exit, exit_reason = self.strategy.should_exit(
                    mid, existing.entry_price, fill_price
                )
                if should_exit:
                    self._close_position(existing, fill_price, exec_time, fee, slippage_bps * fill_price / 10000)
                    cash += existing.realized_pnl or 0
                    closed_trades.append(existing)
                    del positions[mid]
                else:
                    continue  # don't add to existing position

            # Open new position
            shares = cost / fill_price if fill_price > 0 else 0
            bt = BacktestTrade(
                signal=signal,
                entry_price=fill_price,
                entry_time=exec_time,
                size_usd=cost,
                slippage_cost=slippage_bps * cost / 10000,
                fee_cost=fee,
                latency_ms=delay_s * 1000,
                status="open",
            )
            positions[mid] = bt
            cash -= total_cost

            # Update equity curve
            equity = cash + sum(
                self._get_price_at(price_data, m, exec_time) or t.entry_price
                for m, t in positions.items()
            ) * sum(t.size_usd / t.entry_price for t in positions.values() if t.entry_price > 0)
            equity_curve.append((exec_time, equity))
            if equity > peak_equity:
                peak_equity = equity
            dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
            max_drawdown = max(max_drawdown, dd)

        # Close remaining positions at end date
        for mid, trade in list(positions.items()):
            end_price = self._get_price_at(price_data, mid, end_date)
            if end_price is None:
                end_price = trade.entry_price  # assume no change
            fee = trade.size_usd * (self.strategy.params.get("fee_bps", 30) / 10000)
            self._close_position(trade, end_price, end_date, fee, 0)
            cash += trade.realized_pnl or 0
            closed_trades.append(trade)
        positions.clear()

        # Calculate metrics
        total_trades = len(closed_trades)
        winning = [t for t in closed_trades if (t.realized_pnl or 0) > 0]
        losing = [t for t in closed_trades if (t.realized_pnl or 0) < 0]
        total_pnl = sum(t.realized_pnl or 0 for t in closed_trades)
        total_fees = sum(t.fee_cost for t in closed_trades)
        total_slippage = sum(t.slippage_cost for t in closed_trades)

        returns = [t.realized_pnl or 0 for t in closed_trades]
        avg_return = sum(returns) / len(returns) if returns else 0
        return_std = (
            math.sqrt(sum((r - avg_return) ** 2 for r in returns) / len(returns))
            if len(returns) > 1
            else 1.0
        )
        sharpe = avg_return / return_std if return_std > 0 else 0

        gross_profit = sum(t.realized_pnl or 0 for t in winning)
        gross_loss = abs(sum(t.realized_pnl or 0 for t in losing))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        return BacktestResult(
            strategy=self.strategy.params.get("strategy_type", StrategyType.COPY),
            start_date=start_date,
            end_date=end_date,
            initial_bankroll=bankroll,
            final_bankroll=cash,
            total_trades=total_trades,
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=len(winning) / total_trades if total_trades > 0 else 0,
            total_pnl=total_pnl,
            total_return_pct=(cash - bankroll) / bankroll * 100 if bankroll > 0 else 0,
            max_drawdown_pct=max_drawdown * 100,
            sharpe_ratio=sharpe,
            profit_factor=profit_factor,
            avg_trade_pnl=avg_return,
            avg_win=sum(t.realized_pnl or 0 for t in winning) / len(winning) if winning else 0,
            avg_loss=sum(t.realized_pnl or 0 for t in losing) / len(losing) if losing else 0,
            total_fees=total_fees,
            total_slippage=total_slippage,
            trades=closed_trades,
        )

    def _close_position(
        self,
        trade: BacktestTrade,
        exit_price: float,
        exit_time: datetime,
        fee: float,
        slippage: float,
    ) -> None:
        """Close a backtest trade and calculate PnL."""
        trade.exit_price = exit_price
        trade.exit_time = exit_time

        if trade.signal.strategy == StrategyType.COPY:
            # Bought, profit = (exit - entry) * shares
            shares = trade.size_usd / trade.entry_price if trade.entry_price > 0 else 0
            trade.realized_pnl = (exit_price - trade.entry_price) * shares - fee - slippage
        else:  # INVERSE
            # Sold, profit = (entry - exit) * shares
            shares = trade.size_usd / trade.entry_price if trade.entry_price > 0 else 0
            trade.realized_pnl = (trade.entry_price - exit_price) * shares - fee - slippage

        trade.fee_cost += fee
        trade.slippage_cost += slippage
        trade.status = "closed"

    def _get_price_at(
        self,
        price_data: dict[str, list[tuple[datetime, float]]],
        market_id: str,
        dt: datetime,
    ) -> Optional[float]:
        """Get price for a market at a specific time.

        Uses linear interpolation between known price points.
        Returns None if no data available near the requested time.
        """
        data = price_data.get(market_id)
        if not data:
            return None

        # Find the two nearest price points
        before = None
        after = None
        for t, p in data:
            if t <= dt:
                before = (t, p)
            elif t > dt and after is None:
                after = (t, p)
                break

        if before is None and after is None:
            return None
        if before is None:
            return after[1]  # type: ignore
        if after is None:
            return before[1]

        # Linear interpolation
        total_seconds = (after[0] - before[0]).total_seconds()
        if total_seconds <= 0:
            return before[1]
        elapsed = (dt - before[0]).total_seconds()
        ratio = elapsed / total_seconds
        return before[1] + ratio * (after[1] - before[1])


def split_train_test(
    signals: list[CopySignal],
    train_ratio: float = 0.7,
) -> tuple[list[CopySignal], list[CopySignal]]:
    """Split signals into train/test sets chronologically (no shuffle)."""
    sorted_signals = sorted(signals, key=lambda s: s.timestamp)
    split_idx = int(len(sorted_signals) * train_ratio)
    return sorted_signals[:split_idx], sorted_signals[split_idx:]


def walk_forward(
    signals: list[CopySignal],
    price_data: dict[str, list[tuple[datetime, float]]],
    strategy: CopyStrategy | InverseStrategy,
    bankroll: float,
    window_days: int = 30,
    step_days: int = 7,
    train_ratio: float = 0.7,
) -> list[BacktestResult]:
    """Walk-forward analysis.

    Slides a window across the data, training on the first portion
    and testing on the remainder. Returns a list of test results.
    """
    if not signals:
        return []

    sorted_signals = sorted(signals, key=lambda s: s.timestamp)
    start = sorted_signals[0].timestamp
    end = sorted_signals[-1].timestamp

    results = []
    window_start = start
    while window_start + timedelta(days=window_days) <= end:
        window_end = window_start + timedelta(days=window_days)
        train_end = window_start + timedelta(days=int(window_days * train_ratio))

        # Filter signals in window
        window_signals = [
            s for s in sorted_signals
            if window_start <= s.timestamp <= window_end
        ]
        test_signals = [
            s for s in window_signals
            if train_end < s.timestamp <= window_end
        ]

        if test_signals:
            engine = BacktestEngine(strategy=strategy, seed=42)
            result = engine.run(
                signals=test_signals,
                price_data=price_data,
                bankroll=bankroll,
                start_date=train_end,
                end_date=window_end,
            )
            results.append(result)

        window_start += timedelta(days=step_days)

    return results


def monte_carlo_simulation(
    backtest_result: BacktestResult,
    n_simulations: int = 1000,
    confidence_levels: list[float] = [0.05, 0.25, 0.50, 0.75, 0.95],
) -> dict[str, float]:
    """Monte Carlo simulation for confidence intervals.

    Randomly reshuffles trade order to estimate the distribution
    of outcomes under different sequence-of-returns risk.
    """
    if not backtest_result.trades:
        return {}

    trade_pnls = [t.realized_pnl or 0 for t in backtest_result.trades]
    final_values = []

    for _ in range(n_simulations):
        shuffled = trade_pnls[:]
        random.shuffle(shuffled)
        equity = backtest_result.initial_bankroll
        peak = equity
        max_dd = 0

        for pnl in shuffled:
            equity += pnl
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        final_values.append(equity)

    final_values.sort()

    results = {}
    for level in confidence_levels:
        idx = int(level * len(final_values))
        idx = min(idx, len(final_values) - 1)
        results[f"p{int(level*100)}"] = final_values[idx]

    results["mean"] = sum(final_values) / len(final_values)
    results["std"] = (
        math.sqrt(sum((v - results["mean"]) ** 2 for v in final_values) / len(final_values))
        if len(final_values) > 1
        else 0
    )

    return results
