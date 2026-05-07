from __future__ import annotations

import pytest

from unittest.mock import AsyncMock, MagicMock, patch

from pm_bot.cli.backtest_cmd import _run_backtest, _setup_logging, _filter_clob_only, _render_forecast_bias_table
from pm_bot.backtest.engine import BacktestResult, SimulatedTrade


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
            no_compound=False, live=False, compare_forecast=False,
            forecast_penalty=0.05, portfolio=False, seed=None, debug=False,
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
            no_compound=False, live=False, compare_forecast=False,
            forecast_penalty=0.05, portfolio=False, seed=None, debug=False,
        )

    @pytest.mark.asyncio
    @patch("pm_bot.cli.backtest_cmd.get_all_strategies")
    async def test_unknown_strategy(self, mock_strats):
        mock_strats.return_value = {"gopfan2": MagicMock()}
        await _run_backtest(
            strategy="nonexistent", all_strats=False, compare=False,
            bankroll=100.0, days=90, cities_str="NYC", csv_path=None,
            real=False, stop_loss=0.0, kelly=0.25, max_pos=0.10,
            no_compound=False, live=False, compare_forecast=False,
            forecast_penalty=0.05, portfolio=False, seed=None, debug=False,
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
            no_compound=False, live=False, compare_forecast=False,
            forecast_penalty=0.05, portfolio=False, seed=None, debug=False,
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
            no_compound=False, live=False, compare_forecast=False,
            forecast_penalty=0.05, portfolio=False, seed=None, debug=False,
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
            no_compound=False, live=False, compare_forecast=False,
            forecast_penalty=0.05, portfolio=False, seed=None, debug=False,
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
            no_compound=False, live=False, compare_forecast=False,
            forecast_penalty=0.05, portfolio=False, seed=None, debug=False,
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
            no_compound=True, live=False, compare_forecast=False,
            forecast_penalty=0.05, portfolio=False, seed=None, debug=False,
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
            no_compound=False, live=False, compare_forecast=False,
            forecast_penalty=0.05, portfolio=False, seed=None, debug=False,
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
                no_compound=False, live=False, compare_forecast=False,
                forecast_penalty=0.05, portfolio=False, seed=None, debug=False,
            )

    @pytest.mark.asyncio
    @patch("pm_bot.cli.backtest_cmd.BacktestEngine")
    @patch("pm_bot.cli.backtest_cmd.get_all_strategies")
    async def test_seed_parameter(self, mock_strats, mock_engine_cls):
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
            no_compound=False, live=False, compare_forecast=False,
            forecast_penalty=0.05, portfolio=False, seed=42, debug=False,
        )

    @pytest.mark.asyncio
    @patch("pm_bot.cli.backtest_cmd.BacktestEngine")
    @patch("pm_bot.cli.backtest_cmd.get_all_strategies")
    async def test_forecast_penalty_override(self, mock_strats, mock_engine_cls):
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
            no_compound=False, live=False, compare_forecast=False,
            forecast_penalty=0.10, portfolio=False, seed=None, debug=False,
        )

    @pytest.mark.asyncio
    @patch("pm_bot.cli.backtest_cmd.BacktestEngine")
    @patch("pm_bot.cli.backtest_cmd.get_all_strategies")
    async def test_live_mode_implies_real_market_data(self, mock_strats, mock_engine_cls):
        mock_strat = MagicMock()
        mock_strat.name = "gopfan2"
        mock_strats.return_value = {"gopfan2": mock_strat}
        mock_engine = MagicMock()
        mock_engine.run_real = AsyncMock(return_value=[])
        mock_engine_cls.return_value = mock_engine

        await _run_backtest(
            strategy="gopfan2", all_strats=False, compare=False,
            bankroll=100.0, days=90, cities_str="NYC", csv_path=None,
            real=False, stop_loss=0.0, kelly=0.25, max_pos=0.10,
            no_compound=False, live=True, compare_forecast=False,
            forecast_penalty=0.05, portfolio=False, seed=None, debug=False,
        )

        mock_engine.run_real.assert_awaited_once()
        mock_engine.run.assert_not_called()


class TestFilterClobOnly:
    def test_filters_forecast_trades(self):
        trade_clob = SimulatedTrade(
            date="2026-01-15", strategy="test", bucket_key="25-26",
            direction="YES", price=0.5, size_usd=10.0, cost=0.5,
            price_source="clob", filled=True,
        )
        trade_forecast = SimulatedTrade(
            date="2026-01-15", strategy="test", bucket_key="25-26",
            direction="YES", price=0.3, size_usd=10.0, cost=0.5,
            price_source="forecast", filled=True,
        )
        result = BacktestResult(
            strategy_name="test",
            bankroll=100.0,
            final_value=105.0,
            total_pnl=5.0,
            trades=[trade_clob, trade_forecast],
        )
        filtered = _filter_clob_only([result])
        assert len(filtered) == 1
        clob_trades = [t for t in filtered[0].trades if t.filled]
        assert len(clob_trades) == 1
        assert clob_trades[0].price_source == "clob"

    def test_all_clob_trades(self):
        trade = SimulatedTrade(
            date="2026-01-15", strategy="test", bucket_key="25-26",
            direction="YES", price=0.5, size_usd=10.0, cost=0.5,
            price_source="clob", filled=True,
        )
        result = BacktestResult(
            strategy_name="test",
            bankroll=100.0,
            final_value=105.0,
            total_pnl=5.0,
            trades=[trade],
        )
        filtered = _filter_clob_only([result])
        assert len(filtered) == 1
        assert len(filtered[0].trades) == 1

    def test_all_forecast_trades(self):
        trade = SimulatedTrade(
            date="2026-01-15", strategy="test", bucket_key="25-26",
            direction="YES", price=0.3, size_usd=10.0, cost=0.5,
            price_source="forecast", filled=True,
        )
        result = BacktestResult(
            strategy_name="test",
            bankroll=100.0,
            final_value=105.0,
            total_pnl=5.0,
            trades=[trade],
        )
        filtered = _filter_clob_only([result])
        assert len(filtered) == 1
        assert len(filtered[0].trades) == 0


class TestRenderForecastBiasTable:
    def test_renders_table(self):
        all_result = BacktestResult(
            strategy_name="test",
            bankroll=100.0,
            final_value=110.0,
            total_pnl=10.0,
            trades=[
                SimulatedTrade(
                    date="2026-01-15", strategy="test", bucket_key="25-26",
                    direction="YES", price=0.5, size_usd=10.0, cost=0.5,
                    pnl=5.0, price_source="clob", filled=True,
                ),
                SimulatedTrade(
                    date="2026-01-15", strategy="test", bucket_key="25-26",
                    direction="YES", price=0.3, size_usd=10.0, cost=0.5,
                    pnl=3.0, price_source="forecast", filled=True,
                ),
            ],
        )
        clob_result = BacktestResult(
            strategy_name="test",
            bankroll=100.0,
            final_value=105.0,
            total_pnl=5.0,
            trades=[
                SimulatedTrade(
                    date="2026-01-15", strategy="test", bucket_key="25-26",
                    direction="YES", price=0.5, size_usd=10.0, cost=0.5,
                    pnl=5.0, price_source="clob", filled=True,
                ),
            ],
        )
        table = _render_forecast_bias_table([all_result], [clob_result])
        assert table is not None
