"""
Monte Carlo simulator for $100 aggressive snowball strategy.

Runs thousands of simulated equity paths to estimate:
- Survival rate (probability of not going bust)
- Snowball milestones ($500, $2000, $10000)
- Maximum drawdown distribution
- Time to milestones
- Risk of ruin curves

Uses historical trade outcomes from backtest results as the simulation input.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Sequence

from pm_bot.backtest.engine import SimulatedTrade


@dataclass
class MonteCarloResult:
    """Results from a Monte Carlo simulation run."""

    # Core parameters
    initial_bankroll: float
    n_simulations: int
    n_trades_per_sim: int
    kelly_fraction: float
    max_single_pct: float

    # Survival metrics
    survival_rate: float  # % of sims that never went bust
    bankruptcy_rate: float  # % of sims that went bust

    # Snowball milestones
    reach_500_rate: float  # % of sims that reached $500
    reach_2000_rate: float  # % of sims that reached $2000
    reach_10000_rate: float  # % of sims that reached $10000

    # Time to milestones (median trades)
    median_trades_to_500: int | None = None
    median_trades_to_2000: int | None = None
    median_trades_to_10000: int | None = None

    # Equity statistics (final)
    median_final_equity: float = 0.0
    p10_final_equity: float = 0.0  # 10th percentile (pessimistic)
    p90_final_equity: float = 0.0  # 90th percentile (optimistic)
    mean_final_equity: float = 0.0

    # Drawdown
    median_max_drawdown: float = 0.0
    worst_max_drawdown: float = 0.0

    # Raw paths (for visualization)
    equity_paths: list[list[float]] = field(default_factory=list)
    final_equities: list[float] = field(default_factory=list)
    max_drawdowns: list[float] = field(default_factory=list)


@dataclass
class TradeOutcome:
    """A single trade outcome for simulation."""

    pnl: float  # profit/loss in dollars
    win: bool
    cost: float  # total cost (fee + gas)


def extract_trade_outcomes(
    trades: Sequence[SimulatedTrade],
) -> list[TradeOutcome]:
    """Extract trade outcomes from backtest results for Monte Carlo sampling."""
    outcomes = []
    for t in trades:
        if not t.resolved:
            continue
        outcomes.append(
            TradeOutcome(
                pnl=t.pnl,
                win=t.pnl > 0,
                cost=t.cost,
            )
        )
    return outcomes


class MonteCarloSimulator:
    """
    Monte Carlo simulator for aggressive $100 snowball strategies.

    Samples from historical trade outcomes and simulates many equity paths
    to estimate survival rates, milestone probabilities, and risk metrics.
    """

    def __init__(
        self,
        initial_bankroll: float = 100.0,
        n_simulations: int = 1000,
        n_trades_per_sim: int = 200,
        kelly_fraction: float = 0.60,
        max_single_pct: float = 0.50,
        min_notional: float = 0.50,
        consecutive_loss_stop: int | None = None,
    ):
        self.initial_bankroll = initial_bankroll
        self.n_simulations = n_simulations
        self.n_trades_per_sim = n_trades_per_sim
        self.kelly_fraction = kelly_fraction
        self.max_single_pct = max_single_pct
        self.min_notional = min_notional
        self.consecutive_loss_stop = consecutive_loss_stop

    def _size_position(self, bankroll: float, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """Calculate position size using Kelly criterion with $100 aggressive caps.

        For $100 aggressive mode, we use a modified Kelly that:
        1. Calculates raw Kelly from outcomes
        2. Applies kelly_fraction multiplier (0.25-1.00)
        3. Caps at max_single_pct
        4. Ensures minimum bet for lottery tickets
        """
        if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
            return min(bankroll * self.max_single_pct, bankroll)

        # Kelly formula: f* = (p * b - q) / b
        b = abs(avg_win / avg_loss) if avg_loss != 0 else 1.0
        q = 1.0 - win_rate
        raw_kelly = (win_rate * b - q) / b

        if raw_kelly <= 0:
            # For negative EV, use minimum bet (lottery ticket)
            return self.min_notional

        # Apply kelly_fraction multiplier
        # This allows aggressive configs to bet more than conservative ones
        kelly_pct = raw_kelly * self.kelly_fraction
        pct = min(kelly_pct, self.max_single_pct)
        position_size = max(bankroll * pct, self.min_notional)

        return min(position_size, bankroll)

    def _compute_win_rate(self, outcomes: list[TradeOutcome]) -> tuple[float, float, float]:
        """Compute win rate, average win, and average loss from outcomes."""
        wins = [o.pnl for o in outcomes if o.win]
        losses = [o.pnl for o in outcomes if not o.win]

        win_rate = len(wins) / len(outcomes) if outcomes else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        return win_rate, avg_win, avg_loss

    def run(self, outcomes: list[TradeOutcome]) -> MonteCarloResult:
        """
        Run Monte Carlo simulation.

        Args:
            outcomes: Historical trade outcomes to sample from.

        Returns:
            MonteCarloResult with all simulation metrics.
        """
        if not outcomes:
            return self._empty_result()

        win_rate, avg_win, avg_loss = self._compute_win_rate(outcomes)

        equity_paths: list[list[float]] = []
        final_equities: list[float] = []
        max_drawdowns: list[float] = []
        milestones_500: list[int] = []
        milestones_2000: list[int] = []
        milestones_10000: list[int] = []
        bankrupt_count = 0
        survived_count = 0

        rng = random.Random(42)  # Reproducible

        for _ in range(self.n_simulations):
            path = self._simulate_single_path(outcomes, rng, win_rate, avg_win, avg_loss)
            equity_paths.append(path)

            final_eq = path[-1]
            final_equities.append(final_eq)

            # Max drawdown
            peak = path[0]
            max_dd = 0.0
            for eq in path:
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak if peak > 0 else 0
                max_dd = max(max_dd, dd)
            max_drawdowns.append(max_dd)

            # Milestones
            for milestone, store in [
                (500, milestones_500),
                (2000, milestones_2000),
                (10000, milestones_10000),
            ]:
                for i, eq in enumerate(path):
                    if eq >= milestone:
                        store.append(i)
                        break

            # Bankruptcy / survival
            if final_eq < 1.0:  # Less than $1 = bankrupt
                bankrupt_count += 1
            else:
                survived_count += 1

        # Compute statistics
        sorted_final = sorted(final_equities)
        sorted_dd = sorted(max_drawdowns)

        def percentile(data: list[float], p: float) -> float:
            idx = int(len(data) * p / 100)
            return data[min(idx, len(data) - 1)]

        def median_val(data: list[int]) -> int | None:
            if not data:
                return None
            sorted_data = sorted(data)
            return sorted_data[len(sorted_data) // 2]

        return MonteCarloResult(
            initial_bankroll=self.initial_bankroll,
            n_simulations=self.n_simulations,
            n_trades_per_sim=self.n_trades_per_sim,
            kelly_fraction=self.kelly_fraction,
            max_single_pct=self.max_single_pct,
            survival_rate=survived_count / self.n_simulations,
            bankruptcy_rate=bankrupt_count / self.n_simulations,
            reach_500_rate=len(milestones_500) / self.n_simulations,
            reach_2000_rate=len(milestones_2000) / self.n_simulations,
            reach_10000_rate=len(milestones_10000) / self.n_simulations,
            median_trades_to_500=median_val(milestones_500),
            median_trades_to_2000=median_val(milestones_2000),
            median_trades_to_10000=median_val(milestones_10000),
            median_final_equity=percentile(sorted_final, 50),
            p10_final_equity=percentile(sorted_final, 10),
            p90_final_equity=percentile(sorted_final, 90),
            mean_final_equity=sum(final_equities) / len(final_equities),
            median_max_drawdown=percentile(sorted_dd, 50),
            worst_max_drawdown=max(max_drawdowns),
            equity_paths=equity_paths,
            final_equities=final_equities,
            max_drawdowns=max_drawdowns,
        )

    def _simulate_single_path(
        self,
        outcomes: list[TradeOutcome],
        rng: random.Random,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
    ) -> list[float]:
        """Simulate a single equity path."""
        bankroll = self.initial_bankroll
        path = [bankroll]
        consecutive_losses = 0

        for _ in range(self.n_trades_per_sim):
            if bankroll < 1.0:  # Bankrupt
                path.append(0.0)
                continue

            # Check consecutive loss stop
            if self.consecutive_loss_stop and consecutive_losses >= self.consecutive_loss_stop:
                path.append(bankroll)
                continue

            # Size position
            position_size = self._size_position(bankroll, win_rate, avg_win, avg_loss)
            position_size = min(position_size, bankroll)

            # Sample random trade outcome
            outcome = rng.choice(outcomes)

            # Calculate P&L based on position size and outcome
            # For tail-YES lottery: if you bet $1 at 10¢/share, you get 10 shares
            # If it wins, you get $10 (10x), if it loses, you lose $1
            # outcome.pnl represents the actual dollar P&L for a reference bet
            # We need to scale it to our position size
            #
            # The key insight: outcome.pnl is the ACTUAL dollar P&L from a real trade.
            # If outcome.pnl = $5, that means a $1 bet would have profited $5.
            # So for a $10 bet, profit = $50.
            #
            # But we need to be careful: outcome.pnl could be from a $10 bet already.
            # We'll assume outcome.pnl is per-dollar of bet for simplicity.
            if outcome.pnl > 0:
                # Win: profit scales with position size
                # outcome.pnl is profit per $1 bet
                pnl = position_size * outcome.pnl
            else:
                # Loss: lose the position size
                # outcome.pnl is negative, representing loss per $1 bet
                pnl = position_size * outcome.pnl  # This will be negative

            bankroll += pnl
            bankroll = max(bankroll, 0.0)  # Can't go below 0
            path.append(bankroll)

            if outcome.win:
                consecutive_losses = 0
            else:
                consecutive_losses += 1

        return path

    def _empty_result(self) -> MonteCarloResult:
        """Return empty result when no outcomes available."""
        return MonteCarloResult(
            initial_bankroll=self.initial_bankroll,
            n_simulations=0,
            n_trades_per_sim=0,
            kelly_fraction=self.kelly_fraction,
            max_single_pct=self.max_single_pct,
            survival_rate=0.0,
            bankruptcy_rate=0.0,
            reach_500_rate=0.0,
            reach_2000_rate=0.0,
            reach_10000_rate=0.0,
        )


def run_sensitivity_analysis(
    outcomes: list[TradeOutcome],
    initial_bankroll: float = 100.0,
    n_simulations: int = 500,
    n_trades: int = 200,
) -> dict[str, MonteCarloResult]:
    """
    Run Monte Carlo across different Kelly/max-pct combinations.

    Returns a dict mapping strategy name → MonteCarloResult.
    """
    configs = {
        "conservative": (0.25, 0.10),
        "moderate": (0.40, 0.30),
        "aggressive": (0.60, 0.50),
        "very_aggressive": (0.80, 0.70),
        "yolo": (1.00, 0.90),
    }

    results = {}
    for name, (kelly, max_pct) in configs.items():
        sim = MonteCarloSimulator(
            initial_bankroll=initial_bankroll,
            n_simulations=n_simulations,
            n_trades_per_sim=n_trades,
            kelly_fraction=kelly,
            max_single_pct=max_pct,
        )
        results[name] = sim.run(outcomes)

    return results
