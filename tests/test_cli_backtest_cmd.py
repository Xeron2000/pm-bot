from __future__ import annotations

import pytest

from unittest.mock import AsyncMock, MagicMock, patch

from pm_bot.cli.backtest_cmd import _run_backtest, _setup_logging


class TestSetupLogging:
    def test_debug_mode(self):
        _setup_logging(debug=True)

    def test_normal_mode(self):
        _setup_logging(debug=False)


class TestRunBacktest:
    @pytest.mark.asyncio
    @patch("pm_bot.cli.backtest_cmd.BacktestEngine")
    @patch("pm_bot.cli.backtest_cmd.get_all_strategies")
    async def test_specific_strategy(self, mock_strats, mock_engine_cls):
        mock_strat = MagicMock()
        mock_strat.name = "gopfan2"
        mock_strats.return_value = {"gopfan2": mock_strat}
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=[])
        mock_engine_cls.return_value = mock_engine
        await _run_backtest(
            strategy="gopfan2", all_strats=False, compare=False,
            bankroll=100.0, days=90, cities_str="NYC", csv_path=None,
            real=False, stop_loss=0.0, kelly=0.25, max_pos=0.10,
            no_compound=False, debug=False,
        )

    @pytest.mark.asyncio
    @patch("pm_bot.cli.backtest_cmd.BacktestEngine")
    @patch("pm_bot.cli.backtest_cmd.get_all_strategies")
    async def test_all_strategies(self, mock_strats, mock_engine_cls):
        mock_strat = MagicMock()
        mock_strat.name = "gopfan2"
        mock_strats.return_value = {"gopfan2": mock_strat}
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=[])
        mock_engine_cls.return_value = mock_engine
        await _run_backtest(
            strategy=None, all_strats=True, compare=False,
            bankroll=100.0, days=90, cities_str="NYC", csv_path=None,
            real=False, stop_loss=0.0, kelly=0.25, max_pos=0.10,
            no_compound=False, debug=False,
        )

    @pytest.mark.asyncio
    @patch("pm_bot.cli.backtest_cmd.get_all_strategies")
    async def test_unknown_strategy(self, mock_strats):
        mock_strats.return_value = {"gopfan2": MagicMock()}
        await _run_backtest(
            strategy="nonexistent", all_strats=False, compare=False,
            bankroll=100.0, days=90, cities_str="NYC", csv_path=None,
            real=False, stop_loss=0.0, kelly=0.25, max_pos=0.10,
            no_compound=False, debug=False,
        )

    @pytest.mark.asyncio
    @patch("pm_bot.cli.backtest_cmd.render_table")
    @patch("pm_bot.cli.backtest_cmd.BacktestEngine")
    @patch("pm_bot.cli.backtest_cmd.get_all_strategies")
    async def test_with_results(self, mock_strats, mock_engine_cls, mock_render):
        mock_strat = MagicMock()
        mock_strat.name = "gopfan2"
        mock_strats.return_value = {"gopfan2": mock_strat}
        mock_result = MagicMock()
        mock_result.strategy_name = "gopfan2"
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=[mock_result])
        mock_engine_cls.return_value = mock_engine
        await _run_backtest(
            strategy="gopfan2", all_strats=False, compare=False,
            bankroll=100.0, days=90, cities_str="NYC", csv_path=None,
            real=False, stop_loss=0.0, kelly=0.25, max_pos=0.10,
            no_compound=False, debug=False,
        )
        mock_render.assert_called_once()

    @pytest.mark.asyncio
    @patch("pm_bot.cli.backtest_cmd.render_comparison_table")
    @patch("pm_bot.cli.backtest_cmd.BacktestEngine")
    @patch("pm_bot.cli.backtest_cmd.get_all_strategies")
    async def test_compare_mode(self, mock_strats, mock_engine_cls, mock_render):
        mock_strat = MagicMock()
        mock_strat.name = "gopfan2"
        mock_strats.return_value = {"gopfan2": mock_strat}
        mock_result = MagicMock()
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=[mock_result])
        mock_engine_cls.return_value = mock_engine
        await _run_backtest(
            strategy=None, all_strats=False, compare=True,
            bankroll=100.0, days=90, cities_str="NYC", csv_path=None,
            real=False, stop_loss=0.0, kelly=0.25, max_pos=0.10,
            no_compound=False, debug=False,
        )
        mock_render.assert_called_once()

    @pytest.mark.asyncio
    @patch("pm_bot.cli.backtest_cmd.export_csv")
    @patch("pm_bot.cli.backtest_cmd.render_table")
    @patch("pm_bot.cli.backtest_cmd.BacktestEngine")
    @patch("pm_bot.cli.backtest_cmd.get_all_strategies")
    async def test_csv_export(self, mock_strats, mock_engine_cls, mock_render, mock_csv):
        mock_strat = MagicMock()
        mock_strat.name = "gopfan2"
        mock_strats.return_value = {"gopfan2": mock_strat}
        mock_result = MagicMock()
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=[mock_result])
        mock_engine_cls.return_value = mock_engine
        await _run_backtest(
            strategy="gopfan2", all_strats=False, compare=False,
            bankroll=100.0, days=90, cities_str="NYC", csv_path="/tmp/test.csv",
            real=False, stop_loss=0.0, kelly=0.25, max_pos=0.10,
            no_compound=False, debug=False,
        )
        mock_csv.assert_called_once()

    @pytest.mark.asyncio
    @patch("pm_bot.cli.backtest_cmd.BacktestEngine")
    @patch("pm_bot.cli.backtest_cmd.get_all_strategies")
    async def test_real_mode(self, mock_strats, mock_engine_cls):
        mock_strat = MagicMock()
        mock_strat.name = "gopfan2"
        mock_strats.return_value = {"gopfan2": mock_strat}
        mock_engine = MagicMock()
        mock_engine.run_real = AsyncMock(return_value=[])
        mock_engine_cls.return_value = mock_engine
        await _run_backtest(
            strategy="gopfan2", all_strats=False, compare=False,
            bankroll=100.0, days=90, cities_str="NYC", csv_path=None,
            real=True, stop_loss=0.0, kelly=0.25, max_pos=0.10,
            no_compound=False, debug=False,
        )

    @pytest.mark.asyncio
    @patch("pm_bot.cli.backtest_cmd.BacktestEngine")
    @patch("pm_bot.cli.backtest_cmd.get_all_strategies")
    async def test_no_compound(self, mock_strats, mock_engine_cls):
        mock_strat = MagicMock()
        mock_strat.name = "gopfan2"
        mock_strats.return_value = {"gopfan2": mock_strat}
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=[])
        mock_engine_cls.return_value = mock_engine
        await _run_backtest(
            strategy="gopfan2", all_strats=False, compare=False,
            bankroll=100.0, days=90, cities_str="NYC", csv_path=None,
            real=False, stop_loss=0.0, kelly=0.25, max_pos=0.10,
            no_compound=True, debug=False,
        )

    @pytest.mark.asyncio
    @patch("pm_bot.cli.backtest_cmd.BacktestEngine")
    @patch("pm_bot.cli.backtest_cmd.get_all_strategies")
    async def test_cities_str(self, mock_strats, mock_engine_cls):
        mock_strat = MagicMock()
        mock_strat.name = "gopfan2"
        mock_strats.return_value = {"gopfan2": mock_strat}
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=[])
        mock_engine_cls.return_value = mock_engine
        await _run_backtest(
            strategy="gopfan2", all_strats=False, compare=False,
            bankroll=100.0, days=90, cities_str="NYC,London", csv_path=None,
            real=False, stop_loss=0.0, kelly=0.25, max_pos=0.10,
            no_compound=False, debug=False,
        )

    @pytest.mark.asyncio
    @patch("pm_bot.cli.backtest_cmd.get_all_strategies")
    async def test_no_results(self, mock_strats):
        mock_strat = MagicMock()
        mock_strat.name = "gopfan2"
        mock_strats.return_value = {"gopfan2": mock_strat}
        with patch("pm_bot.cli.backtest_cmd.BacktestEngine") as mock_cls:
            mock_engine = MagicMock()
            mock_engine.run = AsyncMock(return_value=[])
            mock_cls.return_value = mock_engine
            await _run_backtest(
                strategy="gopfan2", all_strats=False, compare=False,
                bankroll=100.0, days=90, cities_str="NYC", csv_path=None,
                real=False, stop_loss=0.0, kelly=0.25, max_pos=0.10,
                no_compound=False, debug=False,
            )
