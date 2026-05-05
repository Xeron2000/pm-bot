from __future__ import annotations
import pytest

from unittest.mock import MagicMock, patch

from pm_bot.cli.orders import run_orders


class TestRunOrders:
    @patch("pm_bot.cli.orders.load_config", return_value={})
    @patch("pm_bot.cli.orders.ClobTrader")
    @pytest.mark.asyncio
    async def test_not_configured(self, mock_trader_cls, mock_config):
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = False
        mock_trader_cls.return_value = mock_trader
        await run_orders()

    @patch("pm_bot.cli.orders.load_config", return_value={})
    @patch("pm_bot.cli.orders.ClobTrader")
    @pytest.mark.asyncio
    async def test_no_open_orders(self, mock_trader_cls, mock_config):
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader.get_open_orders.return_value = []
        mock_trader_cls.return_value = mock_trader
        await run_orders()

    @patch("pm_bot.cli.orders.load_config", return_value={})
    @patch("pm_bot.cli.orders.ClobTrader")
    @pytest.mark.asyncio
    async def test_with_open_orders(self, mock_trader_cls, mock_config):
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader.get_open_orders.return_value = [
            {"id": "ord1", "asset_id": "asset1", "side": "BUY", "price": "0.50",
             "original_size": "10", "size_matched": "5", "status": "open"},
        ]
        mock_trader.get_trades.return_value = [
            {"id": "t1", "market": "m1", "side": "SELL", "price": "0.60",
             "size": "5", "status": "filled"},
        ]
        mock_trader.daily_spent = 25.0
        mock_trader_cls.return_value = mock_trader
        await run_orders()

    @patch("pm_bot.cli.orders.load_config", return_value={})
    @patch("pm_bot.cli.orders.ClobTrader")
    @pytest.mark.asyncio
    async def test_orders_fetch_exception(self, mock_trader_cls, mock_config):
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader.get_open_orders.side_effect = Exception("api error")
        mock_trader_cls.return_value = mock_trader
        await run_orders()

    @patch("pm_bot.cli.orders.load_config", return_value={})
    @patch("pm_bot.cli.orders.ClobTrader")
    @pytest.mark.asyncio
    async def test_trades_fetch_exception(self, mock_trader_cls, mock_config):
        mock_trader = MagicMock()
        mock_trader.is_configured.return_value = True
        mock_trader.get_open_orders.return_value = [
            {"id": "ord1", "asset_id": "asset1", "side": "BUY", "price": "0.50",
             "original_size": "10", "size_matched": "0", "status": "open"},
        ]
        mock_trader.get_trades.side_effect = Exception("trades error")
        mock_trader.daily_spent = 5.0
        mock_trader_cls.return_value = mock_trader
        await run_orders()
