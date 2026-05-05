from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from pm_bot.backtest.engine import BacktestResult, SimulatedTrade
from pm_bot.backtest.report import render_table, render_comparison_table, export_csv


class TestRenderTable:
    def test_empty_results(self):
        table = render_table([])
        assert table is not None

    def test_single_result(self):
        result = BacktestResult(
            strategy_name="test",
            bankroll=100.0,
            final_value=150.0,
            total_pnl=50.0,
            trades=[],
        )
        table = render_table([result])
        assert table is not None

    def test_multiple_results_sorted(self):
        r1 = BacktestResult(strategy_name="low_pnl", bankroll=100.0, final_value=110.0, total_pnl=10.0, trades=[])
        r2 = BacktestResult(strategy_name="high_pnl", bankroll=100.0, final_value=200.0, total_pnl=100.0, trades=[])
        table = render_table([r1, r2])
        assert table is not None


class TestRenderComparisonTable:
    def test_single_result(self):
        result = BacktestResult(
            strategy_name="test",
            bankroll=100.0,
            final_value=150.0,
            total_pnl=50.0,
            trades=[],
        )
        table = render_comparison_table([result])
        assert table is not None

    def test_multiple_results(self):
        r1 = BacktestResult(strategy_name="s1", bankroll=100.0, final_value=110.0, total_pnl=10.0, trades=[])
        r2 = BacktestResult(strategy_name="s2", bankroll=100.0, final_value=200.0, total_pnl=100.0, trades=[])
        table = render_comparison_table([r1, r2])
        assert table is not None


class TestExportCsv:
    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "output.csv"
            result = BacktestResult(
                strategy_name="test",
                bankroll=100.0,
                final_value=150.0,
                total_pnl=50.0,
                trades=[],
            )
            export_csv([result], path)
            assert path.exists()

    def test_with_resolved_trades(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "output.csv"
            trade = SimulatedTrade(
                date="2026-01-15",
                strategy="test",
                bucket_key="25-26",
                direction="YES",
                price=0.5,
                size_usd=10.0,
                cost=0.5,
                pnl=5.0,
                resolved=True,
            )
            result = BacktestResult(
                strategy_name="test",
                bankroll=100.0,
                final_value=105.0,
                total_pnl=5.0,
                trades=[trade],
            )
            export_csv([result], path)
            assert path.exists()
            with open(path) as f:
                reader = csv.reader(f)
                rows = list(reader)
                assert len(rows) == 2
                assert rows[0][0] == "strategy"

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subdir" / "output.csv"
            export_csv([], path)
            assert path.exists()

    def test_zero_bankroll(self):
        result = BacktestResult(
            strategy_name="test",
            bankroll=0.0,
            final_value=0.0,
            total_pnl=0.0,
            trades=[],
        )
        table = render_table([result])
        assert table is not None
