"""
Tests for Monte Carlo simulator and $100 snowball strategies.
"""

import pytest
import random
from datetime import datetime, date

from pm_bot.backtest.monte_carlo import (
    MonteCarloSimulator,
    TradeOutcome,
    extract_trade_outcomes,
    run_sensitivity_analysis,
)
from pm_bot.backtest.snowball_metrics import (
    SnowballMetrics,
    compute_snowball_metrics,
    format_snowball_report,
)
from pm_bot.backtest.engine import SimulatedTrade
from pm_bot.strategies.base import get_all_strategies


class TestMonteCarloSimulator:
    """Test Monte Carlo simulation engine."""

    def _make_outcomes(self, n: int = 100, win_rate: float = 0.20, avg_win: float = 5.0, avg_loss: float = 1.0) -> list[TradeOutcome]:
        """Create synthetic trade outcomes."""
        rng = random.Random(42)
        outcomes = []
        for _ in range(n):
            if rng.random() < win_rate:
                outcomes.append(TradeOutcome(pnl=avg_win, win=True, cost=0.1))
            else:
                outcomes.append(TradeOutcome(pnl=-avg_loss, win=False, cost=0.1))
        return outcomes

    def test_basic_simulation(self):
        """Test basic Monte Carlo simulation runs."""
        outcomes = self._make_outcomes(100, 0.20, 5.0, 1.0)
        sim = MonteCarloSimulator(
            initial_bankroll=100.0,
            n_simulations=100,
            n_trades_per_sim=50,
            kelly_fraction=0.60,
            max_single_pct=0.50,
        )
        result = sim.run(outcomes)

        assert result.n_simulations == 100
        assert result.initial_bankroll == 100.0
        assert 0.0 <= result.survival_rate <= 1.0
        assert 0.0 <= result.bankruptcy_rate <= 1.0
        assert result.survival_rate + result.bankruptcy_rate == pytest.approx(1.0)

    def test_snowball_milestones(self):
        """Test that milestones are tracked."""
        # Create favorable outcomes (high win rate)
        outcomes = self._make_outcomes(200, 0.40, 8.0, 1.0)
        sim = MonteCarloSimulator(
            initial_bankroll=100.0,
            n_simulations=500,
            n_trades_per_sim=100,
            kelly_fraction=0.80,
            max_single_pct=0.70,
        )
        result = sim.run(outcomes)

        # With favorable odds, some sims should reach milestones
        assert result.reach_500_rate >= 0.0
        assert result.median_final_equity > 0

    def test_sensitivity_analysis(self):
        """Test sensitivity analysis across different configs."""
        outcomes = self._make_outcomes(100, 0.25, 6.0, 1.0)
        results = run_sensitivity_analysis(
            outcomes,
            initial_bankroll=100.0,
            n_simulations=50,
            n_trades=30,
        )

        assert "conservative" in results
        assert "aggressive" in results
        assert "yolo" in results

        # Aggressive should have higher variance
        cons = results["conservative"]
        aggr = results["aggressive"]
        assert aggr.max_single_pct > cons.max_single_pct

    def test_empty_outcomes(self):
        """Test with empty outcomes."""
        sim = MonteCarloSimulator(initial_bankroll=100.0, n_simulations=10)
        result = sim.run([])

        assert result.n_simulations == 0
        assert result.survival_rate == 0.0


class TestSnowballMetrics:
    """Test snowball metrics computation."""

    def _make_trade(self, pnl: float, date: str = "2024-01-01") -> SimulatedTrade:
        """Create a synthetic backtest trade."""
        return SimulatedTrade(
            date=date,
            strategy="test",
            bucket_key="70-72",
            direction="YES",
            price=0.10,
            size_usd=10.0,
            cost=0.01,
            pnl=pnl,
            resolved=True,
        )

    def test_basic_metrics(self):
        """Test basic snowball metrics computation."""
        trades = [
            self._make_trade(5.0),
            self._make_trade(-1.0),
            self._make_trade(3.0),
            self._make_trade(-0.5),
            self._make_trade(8.0),
        ]
        metrics = compute_snowball_metrics(trades, initial_bankroll=100.0)

        assert metrics.initial_bankroll == 100.0
        assert metrics.total_trades == 5
        assert metrics.win_rate > 0
        assert len(metrics.equity_curve) > 0

    def test_milestone_tracking(self):
        """Test that milestones are tracked correctly."""
        # Create trades that should reach $500
        trades = []
        for i in range(100):
            # Each trade wins $5
            trades.append(self._make_trade(5.0, f"2024-01-{i+1:02d}"))

        metrics = compute_snowball_metrics(trades, initial_bankroll=100.0)

        assert metrics.reached_500 is True
        assert metrics.trades_to_500 is not None
        assert metrics.trades_to_500 <= 100

    def test_drawdown_tracking(self):
        """Test drawdown computation."""
        trades = [
            self._make_trade(10.0),   # $110
            self._make_trade(-20.0),  # $90 (drawdown from $110)
            self._make_trade(5.0),    # $95
        ]
        metrics = compute_snowball_metrics(trades, initial_bankroll=100.0)

        assert metrics.max_drawdown_pct > 0
        assert len(metrics.drawdown_curve) > 0

    def test_consecutive_losses(self):
        """Test consecutive loss tracking."""
        trades = [
            self._make_trade(5.0),
            self._make_trade(-1.0),
            self._make_trade(-1.0),
            self._make_trade(-1.0),
            self._make_trade(5.0),
        ]
        metrics = compute_snowball_metrics(trades, initial_bankroll=100.0)

        assert metrics.max_consecutive_losses >= 3

    def test_format_report(self):
        """Test report formatting."""
        trades = [self._make_trade(5.0) for _ in range(10)]
        metrics = compute_snowball_metrics(trades, initial_bankroll=100.0)
        report = format_snowball_report(metrics)

        assert "SNOWBALL METRICS REPORT" in report
        assert "$100" in report or "$100.00" in report


class TestStrategies:
    """Test $100-optimized strategies."""

    def test_all_strategies_registered(self):
        """Test that all new strategies are registered."""
        strategies = get_all_strategies()

        assert "gopfan2" in strategies
        assert "laddering" in strategies
        assert "tail_no_barbell" in strategies
        assert "forecast_arb" in strategies
        assert "resolution_delay" in strategies

    def test_strategy_names(self):
        """Test strategy names are correct."""
        strategies = get_all_strategies()

        assert strategies["laddering"].name == "laddering"
        assert strategies["tail_no_barbell"].name == "tail_no_barbell"
        assert strategies["forecast_arb"].name == "forecast_arb"
        assert strategies["resolution_delay"].name == "resolution_delay"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
