from __future__ import annotations

from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from pm_bot.cli.app import app

runner = CliRunner()


class TestScanCommand:
    def test_scan_help(self):
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0
        assert "Scan markets" in result.output

    @patch("pm_bot.cli.scan.run_scan", new_callable=AsyncMock)
    def test_scan_default(self, mock_scan):
        mock_scan.return_value = None
        result = runner.invoke(app, ["scan"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.scan.run_scan", new_callable=AsyncMock)
    def test_scan_with_strategy(self, mock_scan):
        mock_scan.return_value = None
        result = runner.invoke(app, ["scan", "--strategy", "gopfan2"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.scan.run_scan", new_callable=AsyncMock)
    def test_scan_with_cities(self, mock_scan):
        mock_scan.return_value = None
        result = runner.invoke(app, ["scan", "--cities", "NYC,HK"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.scan.run_scan", new_callable=AsyncMock)
    def test_scan_all_cities(self, mock_scan):
        mock_scan.return_value = None
        result = runner.invoke(app, ["scan", "--all"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.scan.run_scan", new_callable=AsyncMock)
    def test_scan_with_edge(self, mock_scan):
        mock_scan.return_value = None
        result = runner.invoke(app, ["scan", "--edge", "0.10"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.scan.run_scan", new_callable=AsyncMock)
    def test_scan_verbose(self, mock_scan):
        mock_scan.return_value = None
        result = runner.invoke(app, ["scan", "--verbose"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.scan.run_scan", new_callable=AsyncMock)
    def test_scan_closed(self, mock_scan):
        mock_scan.return_value = None
        result = runner.invoke(app, ["scan", "--closed"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.scan.run_scan", new_callable=AsyncMock)
    def test_scan_observed(self, mock_scan):
        mock_scan.return_value = None
        result = runner.invoke(app, ["scan", "--observed"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.scan.run_scan", new_callable=AsyncMock)
    def test_scan_debug(self, mock_scan):
        mock_scan.return_value = None
        result = runner.invoke(app, ["scan", "--debug"])
        assert result.exit_code == 0


class TestMarketsCommand:
    def test_markets_help(self):
        result = runner.invoke(app, ["markets", "--help"])
        assert result.exit_code == 0
        assert "List current" in result.output

    @patch("pm_bot.cli.markets.run_markets", new_callable=AsyncMock)
    def test_markets_default(self, mock_markets):
        mock_markets.return_value = None
        result = runner.invoke(app, ["markets"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.markets.run_markets", new_callable=AsyncMock)
    def test_markets_with_cities(self, mock_markets):
        mock_markets.return_value = None
        result = runner.invoke(app, ["markets", "--cities", "NYC"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.markets.run_markets", new_callable=AsyncMock)
    def test_markets_all(self, mock_markets):
        mock_markets.return_value = None
        result = runner.invoke(app, ["markets", "--all"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.markets.run_markets", new_callable=AsyncMock)
    def test_markets_closed(self, mock_markets):
        mock_markets.return_value = None
        result = runner.invoke(app, ["markets", "--closed"])
        assert result.exit_code == 0


class TestWatchCommand:
    def test_watch_help(self):
        result = runner.invoke(app, ["watch", "--help"])
        assert result.exit_code == 0
        assert "TUI" in result.output

    @patch("pm_bot.cli.watch.run_watch", new_callable=AsyncMock)
    def test_watch_default(self, mock_watch):
        mock_watch.return_value = None
        result = runner.invoke(app, ["watch"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.watch.run_watch", new_callable=AsyncMock)
    def test_watch_no_ws(self, mock_watch):
        mock_watch.return_value = None
        result = runner.invoke(app, ["watch", "--no-ws"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.watch.run_watch", new_callable=AsyncMock)
    def test_watch_with_interval(self, mock_watch):
        mock_watch.return_value = None
        result = runner.invoke(app, ["watch", "--interval", "30"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.watch.run_watch", new_callable=AsyncMock)
    def test_watch_observed(self, mock_watch):
        mock_watch.return_value = None
        result = runner.invoke(app, ["watch", "--observed"])
        assert result.exit_code == 0


class TestExplainCommand:
    def test_explain_help(self):
        result = runner.invoke(app, ["explain", "--help"])
        assert result.exit_code == 0
        assert "Show detailed" in result.output

    @patch("pm_bot.cli.explain.run_explain", new_callable=AsyncMock)
    def test_explain_with_id(self, mock_explain):
        mock_explain.return_value = None
        result = runner.invoke(app, ["explain", "12345"])
        assert result.exit_code == 0


class TestTradeCommand:
    def test_trade_help(self):
        result = runner.invoke(app, ["trade", "--help"])
        assert result.exit_code == 0
        assert "Scan markets" in result.output

    @patch("pm_bot.cli.trade.run_trade", new_callable=AsyncMock)
    def test_trade_default(self, mock_trade):
        mock_trade.return_value = None
        result = runner.invoke(app, ["trade"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.trade.run_trade", new_callable=AsyncMock)
    def test_trade_confirm(self, mock_trade):
        mock_trade.return_value = None
        result = runner.invoke(app, ["trade", "--confirm"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.trade.run_trade", new_callable=AsyncMock)
    def test_trade_observed(self, mock_trade):
        mock_trade.return_value = None
        result = runner.invoke(app, ["trade", "--observed"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.trade.run_trade", new_callable=AsyncMock)
    def test_trade_with_cities(self, mock_trade):
        mock_trade.return_value = None
        result = runner.invoke(app, ["trade", "--cities", "NYC"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.trade.run_trade", new_callable=AsyncMock)
    def test_trade_all_cities(self, mock_trade):
        mock_trade.return_value = None
        result = runner.invoke(app, ["trade", "--all"])
        assert result.exit_code == 0


class TestSettleCommand:
    def test_settle_help(self):
        result = runner.invoke(app, ["settle", "--help"])
        assert result.exit_code == 0
        assert "Redeem" in result.output

    @patch("pm_bot.cli.settle.run_settle")
    def test_settle_default(self, mock_settle):
        mock_settle.return_value = None
        result = runner.invoke(app, ["settle"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.settle.run_settle")
    def test_settle_list(self, mock_settle):
        mock_settle.return_value = None
        result = runner.invoke(app, ["settle", "--list"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.settle.run_settle")
    def test_settle_all(self, mock_settle):
        mock_settle.return_value = None
        result = runner.invoke(app, ["settle", "--all"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.settle.run_settle")
    def test_settle_with_ids(self, mock_settle):
        mock_settle.return_value = None
        result = runner.invoke(app, ["settle", "--ids", "id1,id2"])
        assert result.exit_code == 0


class TestOrdersCommand:
    def test_orders_help(self):
        result = runner.invoke(app, ["orders", "--help"])
        assert result.exit_code == 0
        assert "Show current" in result.output

    @patch("pm_bot.cli.orders.run_orders", new_callable=AsyncMock)
    def test_orders_default(self, mock_orders):
        mock_orders.return_value = None
        result = runner.invoke(app, ["orders"])
        assert result.exit_code == 0


class TestConfigCommand:
    def test_config_help(self):
        result = runner.invoke(app, ["config", "--help"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.config_cmd.run_config")
    def test_config_show(self, mock_config):
        mock_config.return_value = None
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.config_cmd.run_config")
    def test_config_init(self, mock_config):
        mock_config.return_value = None
        result = runner.invoke(app, ["config", "--init"])
        assert result.exit_code == 0


class TestBacktestCommand:
    def test_backtest_help(self):
        result = runner.invoke(app, ["backtest", "--help"])
        assert result.exit_code == 0
        assert "Run backtest" in result.output

    @patch("pm_bot.cli.backtest_cmd._run_backtest", new_callable=AsyncMock)
    def test_backtest_default(self, mock_bt):
        mock_bt.return_value = None
        result = runner.invoke(app, ["backtest"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.backtest_cmd._run_backtest", new_callable=AsyncMock)
    def test_backtest_with_strategy(self, mock_bt):
        mock_bt.return_value = None
        result = runner.invoke(app, ["backtest", "--strategy", "gopfan2"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.backtest_cmd._run_backtest", new_callable=AsyncMock)
    def test_backtest_all(self, mock_bt):
        mock_bt.return_value = None
        result = runner.invoke(app, ["backtest", "--all"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.backtest_cmd._run_backtest", new_callable=AsyncMock)
    def test_backtest_compare(self, mock_bt):
        mock_bt.return_value = None
        result = runner.invoke(app, ["backtest", "--compare"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.backtest_cmd._run_backtest", new_callable=AsyncMock)
    def test_backtest_real(self, mock_bt):
        mock_bt.return_value = None
        result = runner.invoke(app, ["backtest", "--real"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.backtest_cmd._run_backtest", new_callable=AsyncMock)
    def test_backtest_no_compound(self, mock_bt):
        mock_bt.return_value = None
        result = runner.invoke(app, ["backtest", "--no-compound"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.backtest_cmd._run_backtest", new_callable=AsyncMock)
    def test_backtest_with_bankroll(self, mock_bt):
        mock_bt.return_value = None
        result = runner.invoke(app, ["backtest", "--bankroll", "500"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.backtest_cmd._run_backtest", new_callable=AsyncMock)
    def test_backtest_with_days(self, mock_bt):
        mock_bt.return_value = None
        result = runner.invoke(app, ["backtest", "--days", "30"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.backtest_cmd._run_backtest", new_callable=AsyncMock)
    def test_backtest_with_kelly(self, mock_bt):
        mock_bt.return_value = None
        result = runner.invoke(app, ["backtest", "--kelly", "0.5"])
        assert result.exit_code == 0


class TestDaemonCommands:
    def test_daemon_start_help(self):
        result = runner.invoke(app, ["daemon", "start", "--help"])
        assert result.exit_code == 0
        assert "Start" in result.output

    def test_daemon_stop_help(self):
        result = runner.invoke(app, ["daemon", "stop", "--help"])
        assert result.exit_code == 0
        assert "Stop" in result.output

    def test_daemon_status_help(self):
        result = runner.invoke(app, ["daemon", "status", "--help"])
        assert result.exit_code == 0
        assert "Show daemon" in result.output

    @patch("pm_bot.cli.daemon.daemon_start", new_callable=AsyncMock)
    def test_daemon_start(self, mock_start):
        mock_start.return_value = None
        result = runner.invoke(app, ["daemon", "start"])
        assert result.exit_code == 0

    @patch.dict("os.environ", {"PM_BOT_STOP_LOSS": "0.1"})
    @patch("pm_bot.cli.daemon.daemon_start", new_callable=AsyncMock)
    def test_daemon_start_stop_loss_overrides_env(self, mock_start):
        mock_start.return_value = None
        result = runner.invoke(app, ["daemon", "start", "--dry-run", "--stop-loss", "0.2"])
        assert result.exit_code == 0
        import os
        assert os.environ["PM_BOT_STOP_LOSS"] == "0.2"

    @patch("pm_bot.cli.daemon.daemon_stop", new_callable=AsyncMock)
    def test_daemon_stop(self, mock_stop):
        mock_stop.return_value = None
        result = runner.invoke(app, ["daemon", "stop"])
        assert result.exit_code == 0

    @patch("pm_bot.cli.daemon.daemon_status", new_callable=AsyncMock)
    def test_daemon_status(self, mock_status):
        mock_status.return_value = None
        result = runner.invoke(app, ["daemon", "status"])
        assert result.exit_code == 0

    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        assert result.exit_code == 2
