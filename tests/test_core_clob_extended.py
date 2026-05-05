from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from pm_bot.core.clob import (
    ClobTrader,
    _retry_on_425,
    CLOB_HOST,
    CHAIN_ID,
    MAX_425_RETRIES,
)


class TestRetryOn425:
    def test_success_first_try(self):
        fn = MagicMock(return_value="ok")
        result = _retry_on_425(fn, max_retries=2)
        assert result == "ok"
        assert fn.call_count == 1

    def test_retry_on_425(self):
        err425 = httpx.HTTPStatusError(
            "425", request=MagicMock(), response=MagicMock(status_code=425),
        )
        fn = MagicMock(side_effect=[err425, "ok"])
        with patch("pm_bot.core.clob.time.sleep"):
            result = _retry_on_425(fn, max_retries=2)
        assert result == "ok"
        assert fn.call_count == 2

    def test_non_425_raises(self):
        err500 = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock(status_code=500),
        )
        fn = MagicMock(side_effect=err500)
        with pytest.raises(httpx.HTTPStatusError):
            _retry_on_425(fn, max_retries=2)

    def test_max_retries_exceeded(self):
        err425 = httpx.HTTPStatusError(
            "425", request=MagicMock(), response=MagicMock(status_code=425),
        )
        fn = MagicMock(side_effect=err425)
        with patch("pm_bot.core.clob.time.sleep"):
            with pytest.raises(httpx.HTTPStatusError):
                _retry_on_425(fn, max_retries=1)
        assert fn.call_count == 2


class TestClobTraderInit:
    def test_default_config(self):
        trader = ClobTrader(config={})
        assert trader._daily_spent == 0.0
        assert trader._client is None

    def test_daily_spent_property(self):
        trader = ClobTrader(config={})
        assert trader.daily_spent == 0.0


class TestClobTraderCheckSizing:
    def test_within_limits(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_sizing", return_value={"max_single": 50.0, "max_daily": 200.0}):
            result = trader._check_sizing(10.0)
        assert result is None

    def test_exceeds_max_single(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_sizing", return_value={"max_single": 5.0, "max_daily": 200.0}):
            result = trader._check_sizing(10.0)
        assert result is not None
        assert "max_single" in result

    def test_exceeds_daily(self):
        trader = ClobTrader(config={})
        trader._daily_spent = 195.0
        with patch("pm_bot.core.clob.get_sizing", return_value={"max_single": 50.0, "max_daily": 200.0}):
            result = trader._check_sizing(10.0)
        assert result is not None
        assert "Daily limit" in result


class TestClobTraderPlaceLimitBuy:
    def test_sizing_check_fails(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_sizing", return_value={"max_single": 1.0, "max_daily": 2.0}):
            result = trader.place_limit_buy("token1", 0.5, 10.0)
        assert result is None

    def test_order_exception_returns_none(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_sizing", return_value={"max_single": 50.0, "max_daily": 200.0}):
            with patch.object(trader, "_get_client", side_effect=Exception("no client")):
                result = trader.place_limit_buy("token1", 0.5, 10.0)
        assert result is None

    def test_successful_order(self):
        trader = ClobTrader(config={})
        mock_client = MagicMock()
        mock_client.create_and_post_order.return_value = {"orderID": "ord1"}
        with patch("pm_bot.core.clob.get_sizing", return_value={"max_single": 50.0, "max_daily": 200.0}):
            with patch.object(trader, "_get_client", return_value=mock_client):
                with patch.dict("sys.modules", {
                    "py_clob_client_v2": MagicMock(OrderArgs=MagicMock, OrderType=MagicMock(GTC="GTC"), PartialCreateOrderOptions=MagicMock),
                    "py_clob_client_v2.order_builder": MagicMock(),
                    "py_clob_client_v2.order_builder.constants": MagicMock(BUY="BUY"),
                }):
                    result = trader.place_limit_buy("token1", 0.5, 10.0)
        assert result is not None
        assert trader.daily_spent == 5.0


class TestClobTraderPlaceLimitSell:
    def test_sizing_check_fails(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_sizing", return_value={"max_single": 1.0, "max_daily": 2.0}):
            result = trader.place_limit_sell("token1", 0.5, 10.0)
        assert result is None

    def test_order_exception_returns_none(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_sizing", return_value={"max_single": 50.0, "max_daily": 200.0}):
            with patch.object(trader, "_get_client", side_effect=Exception("no client")):
                result = trader.place_limit_sell("token1", 0.5, 10.0)
        assert result is None

    def test_successful_order(self):
        trader = ClobTrader(config={})
        mock_client = MagicMock()
        mock_client.create_and_post_order.return_value = {"orderID": "ord2"}
        with patch("pm_bot.core.clob.get_sizing", return_value={"max_single": 50.0, "max_daily": 200.0}):
            with patch.object(trader, "_get_client", return_value=mock_client):
                with patch.dict("sys.modules", {
                    "py_clob_client_v2": MagicMock(OrderArgs=MagicMock, OrderType=MagicMock(GTC="GTC"), PartialCreateOrderOptions=MagicMock),
                    "py_clob_client_v2.order_builder": MagicMock(),
                    "py_clob_client_v2.order_builder.constants": MagicMock(SELL="SELL"),
                }):
                    result = trader.place_limit_sell("token1", 0.5, 10.0)
        assert result is not None


class TestClobTraderPlaceMarketBuy:
    def test_sizing_check_fails(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_sizing", return_value={"max_single": 1.0, "max_daily": 2.0}):
            result = trader.place_market_buy("token1", 10.0)
        assert result is None

    def test_order_exception_returns_none(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_sizing", return_value={"max_single": 50.0, "max_daily": 200.0}):
            with patch.object(trader, "_get_client", side_effect=Exception("no client")):
                result = trader.place_market_buy("token1", 10.0)
        assert result is None

    def test_successful_order(self):
        trader = ClobTrader(config={})
        mock_client = MagicMock()
        mock_client.create_and_post_market_order.return_value = {"orderID": "ord3"}
        with patch("pm_bot.core.clob.get_sizing", return_value={"max_single": 50.0, "max_daily": 200.0}):
            with patch.object(trader, "_get_client", return_value=mock_client):
                with patch.dict("sys.modules", {
                    "py_clob_client_v2": MagicMock(MarketOrderArgs=MagicMock, OrderType=MagicMock(FOK="FOK"), PartialCreateOrderOptions=MagicMock),
                    "py_clob_client_v2.order_builder": MagicMock(),
                    "py_clob_client_v2.order_builder.constants": MagicMock(BUY="BUY"),
                }):
                    result = trader.place_market_buy("token1", 10.0)
        assert result is not None
        assert trader.daily_spent == 10.0


class TestClobTraderCancelOrder:
    def test_exception_returns_none(self):
        trader = ClobTrader(config={})
        with patch.object(trader, "_get_client", side_effect=Exception("fail")):
            result = trader.cancel_order("ord1")
        assert result is None

    def test_successful_cancel(self):
        trader = ClobTrader(config={})
        mock_client = MagicMock()
        mock_client.cancel_order.return_value = {"success": True}
        with patch.object(trader, "_get_client", return_value=mock_client):
            with patch.dict("sys.modules", {"py_clob_client_v2": MagicMock(OrderPayload=MagicMock)}):
                result = trader.cancel_order("ord1")
        assert result is not None


class TestClobTraderCancelAll:
    def test_exception_returns_none(self):
        trader = ClobTrader(config={})
        with patch.object(trader, "_get_client", side_effect=Exception("fail")):
            result = trader.cancel_all_orders()
        assert result is None

    def test_successful_cancel_all(self):
        trader = ClobTrader(config={})
        mock_client = MagicMock()
        mock_client.cancel_all.return_value = {"success": True}
        with patch.object(trader, "_get_client", return_value=mock_client):
            result = trader.cancel_all_orders()
        assert result is not None


class TestClobTraderGetOpenOrders:
    def test_exception_returns_empty(self):
        trader = ClobTrader(config={})
        with patch.object(trader, "_get_client", side_effect=Exception("fail")):
            result = trader.get_open_orders()
        assert result == []

    def test_successful(self):
        trader = ClobTrader(config={})
        mock_client = MagicMock()
        mock_client.get_open_orders.return_value = [{"id": "1"}]
        with patch.object(trader, "_get_client", return_value=mock_client):
            with patch.dict("sys.modules", {"py_clob_client_v2": MagicMock(OpenOrderParams=MagicMock)}):
                result = trader.get_open_orders()
        assert result == [{"id": "1"}]

    def test_non_list_response(self):
        trader = ClobTrader(config={})
        mock_client = MagicMock()
        mock_client.get_open_orders.return_value = "not a list"
        with patch.object(trader, "_get_client", return_value=mock_client):
            with patch.dict("sys.modules", {"py_clob_client_v2": MagicMock(OpenOrderParams=MagicMock)}):
                result = trader.get_open_orders()
        assert result == []


class TestClobTraderGetOrderStatus:
    def test_exception_returns_none(self):
        trader = ClobTrader(config={})
        with patch.object(trader, "_get_client", side_effect=Exception("fail")):
            result = trader.get_order_status("ord1")
        assert result is None

    def test_successful(self):
        trader = ClobTrader(config={})
        mock_client = MagicMock()
        mock_client.get_order.return_value = {"id": "ord1", "status": "filled"}
        with patch.object(trader, "_get_client", return_value=mock_client):
            result = trader.get_order_status("ord1")
        assert result is not None


class TestClobTraderGetTrades:
    def test_exception_returns_empty(self):
        trader = ClobTrader(config={})
        with patch.object(trader, "_get_client", side_effect=Exception("fail")):
            result = trader.get_trades()
        assert result == []

    def test_successful(self):
        trader = ClobTrader(config={})
        mock_client = MagicMock()
        mock_client.get_trades.return_value = [{"id": "t1"}]
        with patch.object(trader, "_get_client", return_value=mock_client):
            with patch.dict("sys.modules", {"py_clob_client_v2": MagicMock(TradeParams=MagicMock)}):
                result = trader.get_trades()
        assert result == [{"id": "t1"}]

    def test_non_list_response(self):
        trader = ClobTrader(config={})
        mock_client = MagicMock()
        mock_client.get_trades.return_value = "not a list"
        with patch.object(trader, "_get_client", return_value=mock_client):
            with patch.dict("sys.modules", {"py_clob_client_v2": MagicMock(TradeParams=MagicMock)}):
                result = trader.get_trades()
        assert result == []


class TestClobTraderIsNegRiskMarket:
    def test_exception_returns_true(self):
        trader = ClobTrader(config={})
        with patch.object(trader, "_get_client", side_effect=Exception("fail")):
            result = trader.is_neg_risk_market("token1")
        assert result is True

    def test_successful_true(self):
        trader = ClobTrader(config={})
        mock_client = MagicMock()
        mock_client.get_neg_risk.return_value = True
        with patch.object(trader, "_get_client", return_value=mock_client):
            result = trader.is_neg_risk_market("token1")
        assert result is True

    def test_successful_false(self):
        trader = ClobTrader(config={})
        mock_client = MagicMock()
        mock_client.get_neg_risk.return_value = False
        with patch.object(trader, "_get_client", return_value=mock_client):
            result = trader.is_neg_risk_market("token1")
        assert result is False


class TestClobTraderFetchMarketFeeRateBps:
    def test_success(self):
        trader = ClobTrader(config={})
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"feeRateBps": 50}
        mock_resp.raise_for_status = MagicMock()
        with patch("pm_bot.core.clob.httpx.get", return_value=mock_resp):
            result = trader.fetch_market_fee_rate_bps("cond1")
        assert result == 50

    def test_no_fee_rate(self):
        trader = ClobTrader(config={})
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        with patch("pm_bot.core.clob.httpx.get", return_value=mock_resp):
            result = trader.fetch_market_fee_rate_bps("cond1")
        assert result is None

    def test_exception_returns_none(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.httpx.get", side_effect=Exception("fail")):
            result = trader.fetch_market_fee_rate_bps("cond1")
        assert result is None


class TestClobTraderIsConfigured:
    def test_not_configured(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_private_key", return_value=""):
            with patch("pm_bot.core.clob.get_clob_creds", return_value={"api_key": "", "api_secret": "", "api_passphrase": ""}):
                result = trader.is_configured()
        assert result is False

    def test_configured(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_private_key", return_value="0xabc"):
            with patch("pm_bot.core.clob.get_clob_creds", return_value={"api_key": "key", "api_secret": "sec", "api_passphrase": "phr"}):
                result = trader.is_configured()
        assert result is True


class TestClobTraderGetRedeemablePositions:
    def test_no_key(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_private_key", return_value=""):
            result = trader.get_redeemable_positions()
        assert result == []

    def test_web3_import_error(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_private_key", return_value="0xabc"):
            with patch.dict("sys.modules", {"web3": None}):
                result = trader.get_redeemable_positions()
        assert result == []


class TestClobTraderSettleResolved:
    def test_no_key(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_private_key", return_value=""):
            result = trader.settle_resolved()
        assert result["redeemed"] == 0

    def test_no_poly_web3(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_private_key", return_value="0xabc"):
            with patch.dict("sys.modules", {"poly_web3": None}):
                with patch("pm_bot.core.clob.get_clob_creds", return_value={"api_key": "k", "api_secret": "s", "api_passphrase": "p"}):
                    result = trader.settle_resolved()
        assert result["redeemed"] == 0


class TestClobTraderMergePositions:
    def test_no_key(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_private_key", return_value=""):
            result = trader.merge_positions("cond1", 10.0)
        assert result is None


class TestClobTraderHeartbeat:
    def test_start_and_stop(self):
        trader = ClobTrader(config={})
        with patch.object(trader, "_get_client", side_effect=Exception("no client")):
            trader.start_heartbeat()
            time.sleep(0.1)
            trader.stop_heartbeat()
        assert trader._running is False


class TestClobTraderGetClient:
    def test_no_pk_raises(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_private_key", return_value=""):
            with pytest.raises(ValueError, match="POLY_PK"):
                trader._get_client()

    def test_no_api_key_raises(self):
        trader = ClobTrader(config={})
        with patch("pm_bot.core.clob.get_private_key", return_value="0xabc"):
            with patch("pm_bot.core.clob.get_clob_creds", return_value={"api_key": "", "api_secret": "s", "api_passphrase": "p"}):
                with pytest.raises(ValueError, match="CLOB API credentials"):
                    trader._get_client()

    def test_cached_client(self):
        trader = ClobTrader(config={})
        mock_client = MagicMock()
        trader._client = mock_client
        result = trader._get_client()
        assert result is mock_client


class TestClobTraderRecoverHeartbeatId:
    def test_recovery_success(self):
        trader = ClobTrader(config={})
        mock_client = MagicMock()
        mock_client.post_heartbeat.return_value = {"heartbeat_id": "new_id"}
        with patch.object(trader, "_get_client", return_value=mock_client):
            result = trader._recover_heartbeat_id()
        assert result == "new_id"

    def test_recovery_all_fail(self):
        trader = ClobTrader(config={})
        trader._heartbeat_id = "old_id"
        mock_client = MagicMock()
        mock_client.post_heartbeat.side_effect = Exception("fail")
        with patch.object(trader, "_get_client", return_value=mock_client):
            with patch("pm_bot.core.clob.time.sleep"):
                result = trader._recover_heartbeat_id()
        assert result == "old_id"
    def test_clob_host(self):
        assert CLOB_HOST == "https://clob.polymarket.com"

    def test_chain_id(self):
        assert CHAIN_ID == 137

    def test_max_425_retries(self):
        assert MAX_425_RETRIES == 3
