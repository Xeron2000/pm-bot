from __future__ import annotations

import math

from pm_bot.backtest.metrics import (
    calculate_metrics,
    _compute_daily_returns,
    _sharpe,
    _sortino,
    _max_drawdown,
    _brier_score,
)


class TestComputeDailyReturns:
    def test_empty_series(self):
        assert _compute_daily_returns([]) == []

    def test_single_point(self):
        assert _compute_daily_returns([100.0]) == []

    def test_two_points(self):
        returns = _compute_daily_returns([100.0, 110.0])
        assert len(returns) == 1
        assert abs(returns[0] - 0.1) < 0.001

    def test_zero_prev(self):
        returns = _compute_daily_returns([0.0, 100.0])
        assert returns[0] == 0.0


class TestSharpe:
    def test_empty(self):
        assert _sharpe([]) == 0.0

    def test_zero_variance(self):
        assert _sharpe([0.01, 0.01, 0.01]) == 0.0

    def test_positive_returns(self):
        returns = [0.01, 0.02, -0.01, 0.03]
        sharpe = _sharpe(returns)
        assert sharpe > 0


class TestSortino:
    def test_empty(self):
        assert _sortino([]) == 0.0

    def test_all_positive(self):
        returns = [0.01, 0.02, 0.03]
        sortino = _sortino(returns)
        assert sortino == float("inf")

    def test_with_downside(self):
        returns = [0.01, -0.02, 0.03, -0.01]
        sortino = _sortino(returns)
        assert sortino > 0


class TestMaxDrawdown:
    def test_empty(self):
        assert _max_drawdown([]) == 0.0

    def test_single_point(self):
        assert _max_drawdown([100.0]) == 0.0

    def test_no_drawdown(self):
        series = [100.0, 110.0, 120.0]
        assert _max_drawdown(series) == 0.0

    def test_simple_drawdown(self):
        series = [100.0, 80.0]
        dd = _max_drawdown(series)
        assert abs(dd - 0.2) < 0.001

    def test_recovery_drawdown(self):
        series = [100.0, 120.0, 90.0, 110.0]
        dd = _max_drawdown(series)
        assert abs(dd - 0.25) < 0.001


class TestBrierScore:
    def test_perfect_predictions(self):
        class MockTrade:
            resolved = True
            price = 0.9
            direction = "YES"
            pnl = 1.0
        trades = [MockTrade()]
        brier = _brier_score(trades)
        assert abs(brier - 0.01) < 0.001

    def test_terrible_predictions(self):
        class MockTrade:
            resolved = True
            price = 0.9
            direction = "YES"
            pnl = -1.0
        trades = [MockTrade()]
        brier = _brier_score(trades)
        assert abs(brier - 0.81) < 0.001


class TestCalculateMetrics:
    def test_empty_trades(self):
        result = calculate_metrics([], [100.0])
        assert result["sharpe"] == 0.0
        assert result["win_rate"] == 0.0

    def test_with_resolved_trades(self):
        class MockTrade:
            resolved = True
            pnl = 10.0
            price = 0.6
            direction = "YES"
        trades = [MockTrade(), MockTrade()]
        result = calculate_metrics(trades, [100.0, 110.0, 120.0])
        assert result["win_rate"] == 1.0
        assert result["avg_win"] == 10.0
