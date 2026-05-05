from __future__ import annotations

from unittest.mock import MagicMock, patch

from pm_bot.cli.settle import run_settle


class TestRunSettle:
    @patch("pm_bot.cli.settle.ClobTrader")
    def test_not_configured(self, mock_trader_cls):
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = False
        mock_trader_cls.return_value = mock_trader
        run_settle()

    @patch("pm_bot.cli.settle.ClobTrader")
    def test_list_only_empty(self, mock_trader_cls):
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader.get_redeemable_positions.return_value = []
        mock_trader_cls.return_value = mock_trader
        run_settle(list_only=True)

    @patch("pm_bot.cli.settle.ClobTrader")
    def test_list_only_with_positions(self, mock_trader_cls):
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader.get_redeemable_positions.return_value = [
            {"conditionId": "cond1", "size": 10.0, "outcome": "Yes", "title": "Test Market"},
        ]
        mock_trader_cls.return_value = mock_trader
        run_settle(list_only=True)

    @patch("pm_bot.cli.settle.ClobTrader")
    def test_settle_specific_ids(self, mock_trader_cls):
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader.settle_resolved.return_value = {"redeemed": 1, "errors": []}
        mock_trader_cls.return_value = mock_trader
        run_settle(condition_ids_str="cond1,cond2")

    @patch("pm_bot.cli.settle.ClobTrader")
    def test_settle_all(self, mock_trader_cls):
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader.get_redeemable_positions.return_value = [
            {"conditionId": "cond1", "size": 10.0, "outcome": "Yes"},
            {"conditionId": "cond2", "size": 5.0, "outcome": "No"},
        ]
        mock_trader.settle_resolved.return_value = {"redeemed": 2, "errors": []}
        mock_trader_cls.return_value = mock_trader
        run_settle(all_positions=True)

    @patch("pm_bot.cli.settle.ClobTrader")
    def test_settle_no_positions(self, mock_trader_cls):
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader.get_redeemable_positions.return_value = []
        mock_trader_cls.return_value = mock_trader
        run_settle()

    @patch("pm_bot.cli.settle.ClobTrader")
    def test_settle_no_redeemable(self, mock_trader_cls):
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader.get_redeemable_positions.return_value = [
            {"outcome": "Yes", "size": 0},
        ]
        mock_trader_cls.return_value = mock_trader
        run_settle()

    @patch("pm_bot.cli.settle.ClobTrader")
    def test_settle_with_errors(self, mock_trader_cls):
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader.settle_resolved.return_value = {"redeemed": 0, "errors": ["error1"]}
        mock_trader_cls.return_value = mock_trader
        run_settle(condition_ids_str="cond1")
