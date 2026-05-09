"""
$100 Snowball-specific metrics for tracking aggressive growth strategies.

Tracks:
- Snowball milestones and time-to-milestone
- Consecutive loss streaks
- Bankruptcy risk indicators
- Compounding efficiency
- Drawdown series for visualization
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from pm_bot.backtest.engine import SimulatedTrade


@dataclass
class SnowballMetrics:
    """Metrics specifically designed for $100 aggressive snowball tracking."""

    # Starting capital
    initial_bankroll: float = 100.0

    # Snowball milestones
    reached_500: bool = False
    reached_2000: bool = False
    reached_10000: bool = False
    trades_to_500: int | None = None
    trades_to_2000: int | None = None
    trades_to_10000: int | None = None
    days_to_500: int | None = None
    days_to_2000: int | None = None
    days_to_10000: int | None = None

    # Growth metrics
    max_equity: float = 0.0
    min_equity: float = 0.0
    final_equity: float = 0.0
    total_return_pct: float = 0.0
    cagr_pct: float = 0.0  # Annualized growth rate

    # Risk metrics
    max_drawdown_pct: float = 0.0
    max_drawdown_duration: int = 0  # trades in drawdown
    current_drawdown_pct: float = 0.0

    # Consecutive loss tracking
    max_consecutive_losses: int = 0
    current_consecutive_losses: int = 0
    consecutive_loss_streaks: list[int] = field(default_factory=list)

    # Compounding efficiency
    avg_trade_return_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0  # gross_wins / gross_losses

    # Equity curve (for visualization)
    equity_curve: list[float] = field(default_factory=list)
    drawdown_curve: list[float] = field(default_factory=list)
    trade_dates: list[str] = field(default_factory=list)

    # Bankruptcy risk indicators
    equity_below_50_count: int = 0  # Times equity dropped below $50
    equity_below_20_count: int = 0  # Times equity dropped below $20
    equity_below_10_count: int = 0  # Times equity dropped below $10

    # Position sizing stats
    avg_position_pct: float = 0.0
    max_position_pct: float = 0.0
    total_trades: int = 0


def compute_snowball_metrics(
    trades: Sequence[SimulatedTrade],
    initial_bankroll: float = 100.0,
    daily_trades: int = 3,
) -> SnowballMetrics:
    """
    Compute snowball metrics from backtest trades.

    Args:
        trades: List of completed backtest trades.
        initial_bankroll: Starting capital (default $100).
        daily_trades: Average trades per day (for day estimation).

    Returns:
        SnowballMetrics with all computed values.
    """
    metrics = SnowballMetrics(initial_bankroll=initial_bankroll)

    if not trades:
        return metrics

    # Build equity curve from trades
    bankroll = initial_bankroll
    equity_curve = [bankroll]
    drawdown_curve = [0.0]
    peak = bankroll
    trade_dates = []
    consecutive_losses = 0
    loss_streaks = []
    position_pcts = []
    wins = 0
    gross_wins = 0.0
    gross_losses = 0.0
    equity_below_50 = 0
    equity_below_20 = 0
    equity_below_10 = 0
    in_drawdown_duration = 0
    max_dd_duration = 0

    for i, trade in enumerate(trades):
        if not trade.resolved:
            continue

        pnl = trade.pnl
        bankroll += pnl
        bankroll = max(bankroll, 0.0)
        equity_curve.append(bankroll)

        # Track position sizing
        if trade.size_usd > 0:
            pos_pct = trade.size_usd / max(bankroll - pnl, 0.01)
            position_pcts.append(min(pos_pct, 1.0))

        # Date tracking
        if trade.date:
            trade_dates.append(trade.date)

        # Win/loss tracking
        if pnl > 0:
            wins += 1
            gross_wins += pnl
            if consecutive_losses > 0:
                loss_streaks.append(consecutive_losses)
            consecutive_losses = 0
        else:
            consecutive_losses += 1
            gross_losses += abs(pnl)

        # Drawdown
        if bankroll > peak:
            peak = bankroll
            in_drawdown_duration = 0
        dd = (peak - bankroll) / peak if peak > 0 else 0
        drawdown_curve.append(dd)

        if dd > 0:
            in_drawdown_duration += 1
            max_dd_duration = max(max_dd_duration, in_drawdown_duration)

        # Milestones
        if not metrics.reached_500 and bankroll >= 500:
            metrics.reached_500 = True
            metrics.trades_to_500 = i + 1
            metrics.days_to_500 = (i + 1) // daily_trades
        if not metrics.reached_2000 and bankroll >= 2000:
            metrics.reached_2000 = True
            metrics.trades_to_2000 = i + 1
            metrics.days_to_2000 = (i + 1) // daily_trades
        if not metrics.reached_10000 and bankroll >= 10000:
            metrics.reached_10000 = True
            metrics.trades_to_10000 = i + 1
            metrics.days_to_10000 = (i + 1) // daily_trades

        # Bankruptcy risk
        if bankroll < 50:
            equity_below_50 += 1
        if bankroll < 20:
            equity_below_20 += 1
        if bankroll < 10:
            equity_below_10 += 1

    # Final loss streak
    if consecutive_losses > 0:
        loss_streaks.append(consecutive_losses)

    # Compute derived metrics
    total_trades = len([t for t in trades if t.resolved])
    metrics.total_trades = total_trades
    metrics.max_equity = max(equity_curve) if equity_curve else 0
    metrics.min_equity = min(equity_curve) if equity_curve else 0
    metrics.final_equity = equity_curve[-1] if equity_curve else initial_bankroll
    metrics.total_return_pct = ((metrics.final_equity - initial_bankroll) / initial_bankroll) * 100

    # CAGR (annualized, assuming ~365 trading days)
    if total_trades > 0 and metrics.final_equity > 0:
        days = total_trades // daily_trades
        years = max(days / 365.0, 0.01)
        metrics.cagr_pct = ((metrics.final_equity / initial_bankroll) ** (1 / years) - 1) * 100

    # Drawdown
    metrics.max_drawdown_pct = max(drawdown_curve) * 100 if drawdown_curve else 0
    metrics.current_drawdown_pct = drawdown_curve[-1] * 100 if drawdown_curve else 0
    metrics.max_drawdown_duration = max_dd_duration

    # Win/loss
    metrics.win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    metrics.profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else float("inf")
    metrics.avg_trade_return_pct = (metrics.total_return_pct / total_trades) if total_trades > 0 else 0

    # Consecutive losses
    metrics.max_consecutive_losses = max(loss_streaks) if loss_streaks else 0
    metrics.current_consecutive_losses = consecutive_losses
    metrics.consecutive_loss_streaks = loss_streaks

    # Position sizing
    metrics.avg_position_pct = (sum(position_pcts) / len(position_pcts) * 100) if position_pcts else 0
    metrics.max_position_pct = max(position_pcts) * 100 if position_pcts else 0

    # Bankruptcy risk
    metrics.equity_below_50_count = equity_below_50
    metrics.equity_below_20_count = equity_below_20
    metrics.equity_below_10_count = equity_below_10

    # Curves
    metrics.equity_curve = equity_curve
    metrics.drawdown_curve = drawdown_curve
    metrics.trade_dates = trade_dates

    return metrics


def format_snowball_report(metrics: SnowballMetrics) -> str:
    """Format snowball metrics as a readable report."""
    lines = [
        "=" * 60,
        "💰 $100 SNOWBALL METRICS REPORT",
        "=" * 60,
        "",
        "📈 GROWTH",
        f"  Initial: ${metrics.initial_bankroll:,.2f}",
        f"  Final:   ${metrics.final_equity:,.2f}",
        f"  Return:  {metrics.total_return_pct:+.1f}%",
        f"  CAGR:    {metrics.cagr_pct:+.1f}%",
        f"  Max:     ${metrics.max_equity:,.2f}",
        f"  Min:     ${metrics.min_equity:,.2f}",
        "",
        "🎯 SNOWBALL MILESTONES",
        f"  → $500:    {'✅ ' + str(metrics.trades_to_500) + ' trades' if metrics.reached_500 else '❌ Not reached'}",
        f"  → $2,000:  {'✅ ' + str(metrics.trades_to_2000) + ' trades' if metrics.reached_2000 else '❌ Not reached'}",
        f"  → $10,000: {'✅ ' + str(metrics.trades_to_10000) + ' trades' if metrics.reached_10000 else '❌ Not reached'}",
        "",
        "⚠️ RISK",
        f"  Max Drawdown:      {metrics.max_drawdown_pct:.1f}%",
        f"  DD Duration:       {metrics.max_drawdown_duration} trades",
        f"  Max Consec. Losses: {metrics.max_consecutive_losses}",
        f"  Below $50 count:   {metrics.equity_below_50_count}",
        f"  Below $20 count:   {metrics.equity_below_20_count}",
        f"  Below $10 count:   {metrics.equity_below_10_count}",
        "",
        "📊 STRATEGY",
        f"  Win Rate:       {metrics.win_rate:.1f}%",
        f"  Profit Factor:  {metrics.profit_factor:.2f}",
        f"  Avg Trade P&L:  {metrics.avg_trade_return_pct:.2f}%",
        f"  Avg Position:   {metrics.avg_position_pct:.1f}%",
        f"  Max Position:   {metrics.max_position_pct:.1f}%",
        f"  Total Trades:   {metrics.total_trades}",
        "",
        "=" * 60,
    ]
    return "\n".join(lines)
