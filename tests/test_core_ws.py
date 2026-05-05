from __future__ import annotations

import pytest

from unittest.mock import AsyncMock, patch

from pm_bot.core.ws import MarketWsClient, PriceUpdate, WS_URL, PING_INTERVAL, RECONNECT_DELAY


class TestPriceUpdate:
    def test_defaults(self):
        pu = PriceUpdate(token_id="t1")
        assert pu.token_id == "t1"
        assert pu.best_bid is None
        assert pu.best_ask is None
        assert pu.event_type == ""
        assert pu.data == {}

    def test_with_values(self):
        pu = PriceUpdate(token_id="t1", best_bid=0.5, best_ask=0.55, event_type="book", data={"key": "val"})
        assert pu.best_bid == 0.5
        assert pu.best_ask == 0.55
        assert pu.event_type == "book"
        assert pu.data == {"key": "val"}


class TestMarketWsClientInit:
    def test_init(self):
        client = MarketWsClient()
        assert client._subscribed_ids == set()
        assert client._running is False
        assert client._ws is None


class TestConstants:
    def test_ws_url(self):
        assert WS_URL == "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def test_ping_interval(self):
        assert PING_INTERVAL == 10

    def test_reconnect_delay(self):
        assert RECONNECT_DELAY == 5


class TestMarketWsClientHandleBestBidAsk:
    @pytest.mark.asyncio
    async def test_basic(self):
        client = MarketWsClient()
        data = {"asset_id": "t1", "best_bid": "0.50", "best_ask": "0.55"}
        await client._handle_best_bid_ask(data)
        update = client._queue.get_nowait()
        assert update.token_id == "t1"
        assert update.best_bid == 0.50
        assert update.best_ask == 0.55
        assert update.event_type == "best_bid_ask"

    @pytest.mark.asyncio
    async def test_none_values(self):
        client = MarketWsClient()
        data = {"asset_id": "t1", "best_bid": None, "best_ask": None}
        await client._handle_best_bid_ask(data)
        update = client._queue.get_nowait()
        assert update.best_bid is None
        assert update.best_ask is None


class TestMarketWsClientHandlePriceChange:
    @pytest.mark.asyncio
    async def test_basic(self):
        client = MarketWsClient()
        data = {"asset_id": "t1", "best_bid": "0.45", "best_ask": "0.50"}
        await client._handle_price_change(data)
        update = client._queue.get_nowait()
        assert update.event_type == "price_change"

    @pytest.mark.asyncio
    async def test_none_values(self):
        client = MarketWsClient()
        data = {"asset_id": "t1"}
        await client._handle_price_change(data)
        update = client._queue.get_nowait()
        assert update.best_bid is None


class TestMarketWsClientHandleLastTrade:
    @pytest.mark.asyncio
    async def test_basic(self):
        client = MarketWsClient()
        data = {"asset_id": "t1", "price": 0.55}
        await client._handle_last_trade(data)
        update = client._queue.get_nowait()
        assert update.event_type == "last_trade_price"
        assert update.data["price"] == 0.55

    @pytest.mark.asyncio
    async def test_no_price(self):
        client = MarketWsClient()
        data = {"asset_id": "t1"}
        await client._handle_last_trade(data)
        update = client._queue.get_nowait()
        assert update.data["price"] is None


class TestMarketWsClientHandleBook:
    @pytest.mark.asyncio
    async def test_basic(self):
        client = MarketWsClient()
        data = {"asset_id": "t1", "bids": [], "asks": []}
        await client._handle_book(data)
        update = client._queue.get_nowait()
        assert update.event_type == "book"

    @pytest.mark.asyncio
    async def test_market_fallback(self):
        client = MarketWsClient()
        data = {"market": "t2", "bids": [], "asks": []}
        await client._handle_book(data)
        update = client._queue.get_nowait()
        assert update.token_id == "t2"


class TestMarketWsClientSendSubscribe:
    @pytest.mark.asyncio
    async def test_no_ws(self):
        client = MarketWsClient()
        client._ws = None
        await client._send_subscribe(["t1", "t2"])
        assert "t1" not in client._subscribed_ids
        assert "t2" not in client._subscribed_ids

    @pytest.mark.asyncio
    async def test_with_ws(self):
        client = MarketWsClient()
        mock_ws = AsyncMock()
        client._ws = mock_ws
        await client._send_subscribe(["t1"])
        mock_ws.send.assert_called_once()
        assert "t1" in client._subscribed_ids

    @pytest.mark.asyncio
    async def test_send_failure(self):
        client = MarketWsClient()
        mock_ws = AsyncMock()
        mock_ws.send.side_effect = Exception("fail")
        client._ws = mock_ws
        await client._send_subscribe(["t1"])
        assert "t1" not in client._subscribed_ids


class TestMarketWsClientSubscribe:
    @pytest.mark.asyncio
    async def test_with_ws(self):
        client = MarketWsClient()
        mock_ws = AsyncMock()
        client._ws = mock_ws
        await client.subscribe(["t1", "t2"])
        assert "t1" in client._subscribed_ids
        assert "t2" in client._subscribed_ids
        mock_ws.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_without_ws(self):
        client = MarketWsClient()
        client._ws = None
        await client.subscribe(["t1"])
        assert "t1" in client._subscribed_ids

    @pytest.mark.asyncio
    async def test_send_failure(self):
        client = MarketWsClient()
        mock_ws = AsyncMock()
        mock_ws.send.side_effect = Exception("fail")
        client._ws = mock_ws
        await client.subscribe(["t1"])
        assert "t1" not in client._subscribed_ids


class TestMarketWsClientUnsubscribe:
    @pytest.mark.asyncio
    async def test_with_ws(self):
        client = MarketWsClient()
        client._subscribed_ids = {"t1", "t2"}
        mock_ws = AsyncMock()
        client._ws = mock_ws
        await client.unsubscribe(["t1"])
        assert "t1" not in client._subscribed_ids
        assert "t2" in client._subscribed_ids

    @pytest.mark.asyncio
    async def test_without_ws(self):
        client = MarketWsClient()
        client._subscribed_ids = {"t1", "t2"}
        client._ws = None
        await client.unsubscribe(["t1"])
        assert "t1" not in client._subscribed_ids

    @pytest.mark.asyncio
    async def test_send_failure(self):
        client = MarketWsClient()
        client._subscribed_ids = {"t1"}
        mock_ws = AsyncMock()
        mock_ws.send.side_effect = Exception("fail")
        client._ws = mock_ws
        await client.unsubscribe(["t1"])
        assert "t1" in client._subscribed_ids


class TestMarketWsClientUpdates:
    @pytest.mark.asyncio
    async def test_get_update(self):
        client = MarketWsClient()
        await client._queue.put(PriceUpdate(token_id="t1", event_type="test"))
        update = await client.updates()
        assert update.token_id == "t1"


class TestMarketWsClientStop:
    def test_stop(self):
        client = MarketWsClient()
        client._running = True
        client.stop()
        assert client._running is False


class TestMarketWsClientRecvLoop:
    @pytest.mark.asyncio
    async def test_recv_loop_pong(self):
        client = MarketWsClient()
        client._running = True
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=["PONG", Exception("break")])
        with patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=["PONG", Exception("break")]):
            await client._recv_loop(mock_ws)

    @pytest.mark.asyncio
    async def test_recv_loop_book_event(self):
        import json
        client = MarketWsClient()
        client._running = True
        mock_ws = AsyncMock()
        msg = json.dumps({"event_type": "book", "asset_id": "t1", "bids": [], "asks": []})
        mock_ws.recv = AsyncMock(side_effect=[msg, Exception("break")])
        with patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=[msg, Exception("break")]):
            await client._recv_loop(mock_ws)

    @pytest.mark.asyncio
    async def test_recv_loop_price_change(self):
        import json
        client = MarketWsClient()
        client._running = True
        mock_ws = AsyncMock()
        msg = json.dumps({"event_type": "price_change", "asset_id": "t1", "best_bid": "0.5", "best_ask": "0.55"})
        mock_ws.recv = AsyncMock(side_effect=[msg, Exception("break")])
        with patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=[msg, Exception("break")]):
            await client._recv_loop(mock_ws)

    @pytest.mark.asyncio
    async def test_recv_loop_last_trade(self):
        import json
        client = MarketWsClient()
        client._running = True
        mock_ws = AsyncMock()
        msg = json.dumps({"event_type": "last_trade_price", "asset_id": "t1", "price": 0.55})
        mock_ws.recv = AsyncMock(side_effect=[msg, Exception("break")])
        with patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=[msg, Exception("break")]):
            await client._recv_loop(mock_ws)

    @pytest.mark.asyncio
    async def test_recv_loop_best_bid_ask(self):
        import json
        client = MarketWsClient()
        client._running = True
        mock_ws = AsyncMock()
        msg = json.dumps({"event_type": "best_bid_ask", "asset_id": "t1", "best_bid": "0.5", "best_ask": "0.55"})
        mock_ws.recv = AsyncMock(side_effect=[msg, Exception("break")])
        with patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=[msg, Exception("break")]):
            await client._recv_loop(mock_ws)

    @pytest.mark.asyncio
    async def test_recv_loop_tick_size_change(self):
        import json
        client = MarketWsClient()
        client._running = True
        mock_ws = AsyncMock()
        msg = json.dumps({"event_type": "tick_size_change", "asset_id": "t1"})
        mock_ws.recv = AsyncMock(side_effect=[msg, Exception("break")])
        with patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=[msg, Exception("break")]):
            await client._recv_loop(mock_ws)

    @pytest.mark.asyncio
    async def test_recv_loop_unknown_event(self):
        import json
        client = MarketWsClient()
        client._running = True
        mock_ws = AsyncMock()
        msg = json.dumps({"event_type": "unknown_event", "asset_id": "t1"})
        mock_ws.recv = AsyncMock(side_effect=[msg, Exception("break")])
        with patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=[msg, Exception("break")]):
            await client._recv_loop(mock_ws)

    @pytest.mark.asyncio
    async def test_recv_loop_timeout_ping(self):
        client = MarketWsClient()
        client._running = True
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        with patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=[TimeoutError, Exception("break")]):
            await client._recv_loop(mock_ws)

    @pytest.mark.asyncio
    async def test_recv_loop_timeout_send_fails(self):
        client = MarketWsClient()
        client._running = True
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=Exception("send fail"))
        with patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=[TimeoutError]):
            await client._recv_loop(mock_ws)


class TestMarketWsClientConnect:
    @pytest.mark.asyncio
    async def test_connect_sets_running(self):
        client = MarketWsClient()
        client._running = True
        assert client._running is True
        client.stop()
