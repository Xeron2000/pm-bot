from __future__ import annotations
import pytest

from unittest.mock import AsyncMock, MagicMock, patch

from pm_bot.cli.notifications import (
    send_discord,
    send_telegram,
    format_order_message,
    format_circuit_breaker_message,
    format_daily_summary_message,
    format_daemon_message,
    notify,
)


class TestFormatOrderMessage:
    def test_created(self):
        msg = format_order_message("created", "gopfan2", "YES", "NYC", "23C", 0.15, 0.10, "ord123")
        assert "CREATED" in msg
        assert "gopfan2" in msg
        assert "YES" in msg

    def test_filled(self):
        msg = format_order_message("filled", "gopfan2", "NO", "NYC", "23C", 0.85, 0.10, "ord123")
        assert "FILLED" in msg

    def test_cancelled(self):
        msg = format_order_message("cancelled", "gopfan2", "YES", "NYC", "23C", 0.15, 0.10, "ord123")
        assert "CANCELLED" in msg

    def test_no_order_id(self):
        msg = format_order_message("created", "gopfan2", "YES", "NYC", "23C", 0.15, 0.10)
        assert "Order" not in msg

    def test_with_order_id(self):
        msg = format_order_message("created", "gopfan2", "YES", "NYC", "23C", 0.15, 0.10, "ord123")
        assert "ord123"[:12] in msg

    def test_unknown_action(self):
        msg = format_order_message("unknown", "gopfan2", "YES", "NYC", "23C", 0.15, 0.10)
        assert "UNKNOWN" in msg


class TestFormatCircuitBreakerMessage:
    def test_level1(self):
        msg = format_circuit_breaker_message(1, "L1 reason", 500.0, 0.5)
        assert "L1" in msg
        assert "$500.00" in msg

    def test_level2(self):
        msg = format_circuit_breaker_message(2, "L2 reason", 500.0, 0.25)
        assert "L2" in msg

    def test_level3(self):
        msg = format_circuit_breaker_message(3, "L3 reason", 500.0, 0.0)
        assert "L3" in msg

    def test_unknown_level(self):
        msg = format_circuit_breaker_message(5, "unknown", 500.0, 1.0)
        assert "L5" in msg


class TestFormatDailySummaryMessage:
    def test_basic(self):
        msg = format_daily_summary_message("2026-01-15", 10.0, 5, 3, 2, 500.0)
        assert "2026-01-15" in msg
        assert "$10.00" in msg
        assert "W:3" in msg

    def test_zero_trades(self):
        msg = format_daily_summary_message("2026-01-15", 0.0, 0, 0, 0, 500.0)
        assert "0%" in msg


class TestFormatDaemonMessage:
    def test_start(self):
        msg = format_daemon_message("start")
        assert "START" in msg

    def test_stop(self):
        msg = format_daemon_message("stop")
        assert "STOP" in msg

    def test_crash_recovery(self):
        msg = format_daemon_message("crash_recovery", "reconciling")
        assert "CRASH_RECOVERY" in msg
        assert "reconciling" in msg

    def test_unknown_event(self):
        msg = format_daemon_message("unknown")
        assert "UNKNOWN" in msg

    def test_no_detail(self):
        msg = format_daemon_message("start")
        assert "\n  " not in msg


class TestSendDiscord:
    @patch("pm_bot.cli.notifications.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_empty_url(self, mock_client_cls):
        result = await send_discord("", "test")
        assert result is False

    @patch("pm_bot.cli.notifications.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_success(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        result = await send_discord("https://example.com/webhook", "test")
        assert result is True

    @patch("pm_bot.cli.notifications.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_http_error(self, mock_client_cls):
        import httpx
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.HTTPError("fail")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        result = await send_discord("https://example.com/webhook", "test")
        assert result is False


class TestSendTelegram:
    @pytest.mark.asyncio
    async def test_empty_token(self):
        result = await send_telegram("", "123", "test")
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_chat_id(self):
        result = await send_telegram("token", "", "test")
        assert result is False

    @patch("pm_bot.cli.notifications.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_success(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        result = await send_telegram("token", "123", "test")
        assert result is True

    @patch("pm_bot.cli.notifications.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_http_error(self, mock_client_cls):
        import httpx
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.HTTPError("fail")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        result = await send_telegram("token", "123", "test")
        assert result is False


class TestNotify:
    @patch("pm_bot.cli.notifications.send_telegram", new_callable=AsyncMock)
    @patch("pm_bot.cli.notifications.send_discord", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_notify_basic(self, mock_discord, mock_telegram):
        mock_discord.return_value = True
        mock_telegram.return_value = True
        config = {
            "notifications": {
                "discord": {"webhook_url": "https://example.com"},
                "telegram": {"bot_token": "tok", "chat_id": "123"},
            }
        }
        await notify(config, "created", "gopfan2", "YES", "NYC", "23C", 0.15, 0.10)
        mock_discord.assert_called_once()
        mock_telegram.assert_called_once()

    @patch("pm_bot.cli.notifications.send_telegram", new_callable=AsyncMock)
    @patch("pm_bot.cli.notifications.send_discord", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_notify_no_config(self, mock_discord, mock_telegram):
        await notify({}, "created", "gopfan2", "YES", "NYC", "23C", 0.15, 0.10)
        mock_discord.assert_called_once_with("", "🟢 <b>CREATED</b> | gopfan2 | NYC\n  YES 23C @ 0.15\n  Edge: 10.0%")
        mock_telegram.assert_called_once_with("", "", "🟢 <b>CREATED</b> | gopfan2 | NYC\n  YES 23C @ 0.15\n  Edge: 10.0%")
