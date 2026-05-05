from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pm_bot.cli.daemon import (
    TradingDaemon,
    daemon_start,
    daemon_stop,
    daemon_status,
    _is_daemon_running,
    _estimate_hours_to_resolution,
    _setup_logging,
    _fetch_forecast_at,
)


class TestEstimateHoursToResolution:
    def test_valid_date(self):
        result = _estimate_hours_to_resolution("2099-01-01")
        assert result is not None
        assert result > 0

    def test_empty_string(self):
        result = _estimate_hours_to_resolution("")
        assert result is None

    def test_invalid_format(self):
        result = _estimate_hours_to_resolution("not-a-date")
        assert result is None

    def test_none(self):
        result = _estimate_hours_to_resolution(None)
        assert result is None

    def test_past_date(self):
        result = _estimate_hours_to_resolution("2020-01-01")
        assert result is not None
        assert result == 0.0


class TestIsDaemonRunning:
    @patch("pm_bot.cli.daemon.PID_FILE")
    def test_no_pid_file(self, mock_pid):
        mock_pid.exists.return_value = False
        assert _is_daemon_running() is False

    @patch("pm_bot.cli.daemon.PID_FILE")
    def test_stale_pid_file(self, mock_pid):
        mock_pid.exists.return_value = True
        mock_pid.read_text.return_value = "99999999"
        with patch("pm_bot.cli.daemon.os.kill", side_effect=ProcessLookupError):
            mock_pid.unlink.return_value = None
            assert _is_daemon_running() is False

    @patch("pm_bot.cli.daemon.PID_FILE")
    def test_running_process(self, mock_pid):
        mock_pid.exists.return_value = True
        mock_pid.read_text.return_value = str(1)
        with patch("pm_bot.cli.daemon.os.kill"):
            assert _is_daemon_running() is True

    @patch("pm_bot.cli.daemon.PID_FILE")
    def test_permission_error(self, mock_pid):
        mock_pid.exists.return_value = True
        mock_pid.read_text.return_value = "1"
        with patch("pm_bot.cli.daemon.os.kill", side_effect=PermissionError):
            mock_pid.unlink.return_value = None
            assert _is_daemon_running() is False

    @patch("pm_bot.cli.daemon.PID_FILE")
    def test_value_error(self, mock_pid):
        mock_pid.exists.return_value = True
        mock_pid.read_text.return_value = "not_a_pid"
        mock_pid.unlink.return_value = None
        assert _is_daemon_running() is False


class TestSetupLogging:
    def test_debug(self):
        _setup_logging(debug=True)

    def test_no_debug(self):
        _setup_logging(debug=False)


class TestTradingDaemonInit:
    def test_default_config(self):
        daemon = TradingDaemon({})
        assert daemon.bankroll > 0
        assert daemon.scan_interval > 0
        assert daemon.risk_manager is not None

    def test_custom_config(self):
        config = {
            "risk": {"circuit_breaker_l1": 0.10},
            "daemon": {"scan_interval": 600},
            "sizing": {"bankroll": 1000.0},
        }
        daemon = TradingDaemon(config)
        assert daemon.scan_interval == 600

    def test_env_override(self):
        with patch.dict("os.environ", {"PM_BOT_BANKROLL": "2000"}):
            daemon = TradingDaemon({})
            assert daemon.bankroll == 2000.0


class TestTradingDaemonWriteHeartbeat:
    def test_write_heartbeat(self, tmp_path):
        daemon = TradingDaemon({})
        hb_path = tmp_path / "heartbeat"
        daemon.heartbeat_path = hb_path
        daemon._write_heartbeat()
        assert hb_path.exists()
        data = json.loads(hb_path.read_text())
        assert data["status"] == "running"
        assert data["pid"] > 0

    def test_write_heartbeat_failure(self):
        daemon = TradingDaemon({})
        daemon.heartbeat_path = Path("/nonexistent/path/heartbeat")
        daemon._write_heartbeat()


class TestTradingDaemonRemovePid:
    @patch("pm_bot.cli.daemon.PID_FILE")
    def test_remove_pid(self, mock_pid):
        daemon = TradingDaemon({})
        mock_pid.unlink.return_value = None
        daemon._remove_pid()

    @patch("pm_bot.cli.daemon.PID_FILE")
    def test_remove_pid_error(self, mock_pid):
        daemon = TradingDaemon({})
        mock_pid.unlink.side_effect = Exception("fail")
        daemon._remove_pid()


class TestTradingDaemonHandleSignals:
    def test_sigterm(self):
        daemon = TradingDaemon({})
        daemon._handle_sigterm()
        assert daemon.shutdown_event.is_set()

    def test_sigusr1(self):
        daemon = TradingDaemon({})
        with patch("pm_bot.cli.daemon.load_config", return_value={"new": True}):
            daemon._handle_sigusr1()
            assert daemon.config == {"new": True}

    def test_sigusr1_config_reload_failure(self):
        daemon = TradingDaemon({})
        with patch("pm_bot.cli.daemon.load_config", side_effect=Exception("fail")):
            daemon._handle_sigusr1()


class TestTradingDaemonAutoSettle:
    @pytest.mark.asyncio
    async def test_not_configured(self):
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.is_configured.return_value = False
        await daemon._auto_settle()

    @pytest.mark.asyncio
    async def test_no_positions(self):
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.is_configured.return_value = True
        daemon.trader.get_redeemable_positions.return_value = []
        await daemon._auto_settle()

    @pytest.mark.asyncio
    async def test_with_positions(self):
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.is_configured.return_value = True
        daemon.trader.get_redeemable_positions.return_value = [
            {"conditionId": "cond1", "size": 10.0},
        ]
        daemon.trader.settle_resolved.return_value = {"redeemed": 1}
        await daemon._auto_settle()
        assert daemon.bankroll > 500.0

    @pytest.mark.asyncio
    async def test_settle_exception(self):
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.is_configured.return_value = True
        daemon.trader.get_redeemable_positions.side_effect = Exception("fail")
        await daemon._auto_settle()

    @pytest.mark.asyncio
    async def test_no_condition_ids(self):
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.is_configured.return_value = True
        daemon.trader.get_redeemable_positions.return_value = [
            {"size": 10.0},
        ]
        await daemon._auto_settle()

    @pytest.mark.asyncio
    async def test_redeemed_zero(self):
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.is_configured.return_value = True
        daemon.trader.get_redeemable_positions.return_value = [
            {"conditionId": "cond1", "size": 10.0},
        ]
        daemon.trader.settle_resolved.return_value = {"redeemed": 0}
        await daemon._auto_settle()


class TestTradingDaemonExecuteTrade:
    @pytest.mark.asyncio
    async def test_size_too_small(self):
        from pm_bot.models.market import Recommendation, WeatherEvent, TemperatureBucket
        ev = WeatherEvent(event_id="ev1", title="Test", slug="test", city="NYC",
                          date="2026-01-15", measure_type="high", buckets=[])
        bucket = TemperatureBucket(market_id="m1", question="23C", temp_low=23.0,
                                   temp_high=23.0, temp_unit="C", yes_price=0.15,
                                   no_price=0.85, volume=500.0)
        rec = Recommendation(strategy="test", event=ev, bucket=bucket,
                             direction="YES", edge=0.10, reasoning="test",
                             size_usd=0.5, kelly_fraction=0.1)
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        await daemon._execute_trade(rec)

    @pytest.mark.asyncio
    async def test_yes_direction(self):
        from pm_bot.models.market import Recommendation, WeatherEvent, TemperatureBucket
        ev = WeatherEvent(event_id="ev1", title="Test", slug="test", city="NYC",
                          date="2026-01-15", measure_type="high", buckets=[])
        bucket = TemperatureBucket(market_id="m1", question="23C", temp_low=23.0,
                                   temp_high=23.0, temp_unit="C", yes_price=0.50,
                                   no_price=0.50, volume=500.0)
        rec = Recommendation(strategy="test", event=ev, bucket=bucket,
                             direction="YES", edge=0.10, reasoning="test",
                             size_usd=10.0, kelly_fraction=0.1)
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.place_limit_buy.return_value = {"orderID": "ord1"}
        daemon.db = MagicMock()
        daemon.db.record_trade.return_value = True
        with patch("pm_bot.cli.daemon.notify", new_callable=AsyncMock):
            await daemon._execute_trade(rec)
        daemon.trader.place_limit_buy.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_direction(self):
        from pm_bot.models.market import Recommendation, WeatherEvent, TemperatureBucket
        ev = WeatherEvent(event_id="ev1", title="Test", slug="test", city="NYC",
                          date="2026-01-15", measure_type="high", buckets=[])
        bucket = TemperatureBucket(market_id="m1", question="23C", temp_low=23.0,
                                   temp_high=23.0, temp_unit="C", yes_price=0.50,
                                   no_price=0.50, volume=500.0)
        rec = Recommendation(strategy="test", event=ev, bucket=bucket,
                             direction="NO", edge=0.10, reasoning="test",
                             size_usd=10.0, kelly_fraction=0.1)
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.place_limit_sell.return_value = {"orderID": "ord2"}
        daemon.db = MagicMock()
        daemon.db.record_trade.return_value = True
        with patch("pm_bot.cli.daemon.notify", new_callable=AsyncMock):
            await daemon._execute_trade(rec)
        daemon.trader.place_limit_sell.assert_called_once()

    @pytest.mark.asyncio
    async def test_trade_failure(self):
        from pm_bot.models.market import Recommendation, WeatherEvent, TemperatureBucket
        ev = WeatherEvent(event_id="ev1", title="Test", slug="test", city="NYC",
                          date="2026-01-15", measure_type="high", buckets=[])
        bucket = TemperatureBucket(market_id="m1", question="23C", temp_low=23.0,
                                   temp_high=23.0, temp_unit="C", yes_price=0.50,
                                   no_price=0.50, volume=500.0)
        rec = Recommendation(strategy="test", event=ev, bucket=bucket,
                             direction="YES", edge=0.10, reasoning="test",
                             size_usd=10.0, kelly_fraction=0.1)
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.place_limit_buy.return_value = None
        await daemon._execute_trade(rec)

    @pytest.mark.asyncio
    async def test_zero_price(self):
        from pm_bot.models.market import Recommendation, WeatherEvent, TemperatureBucket
        ev = WeatherEvent(event_id="ev1", title="Test", slug="test", city="NYC",
                          date="2026-01-15", measure_type="high", buckets=[])
        bucket = TemperatureBucket(market_id="m1", question="23C", temp_low=23.0,
                                   temp_high=23.0, temp_unit="C", yes_price=0.0,
                                   no_price=1.0, volume=500.0)
        rec = Recommendation(strategy="test", event=ev, bucket=bucket,
                             direction="YES", edge=0.10, reasoning="test",
                             size_usd=10.0, kelly_fraction=0.1)
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.place_limit_buy.return_value = {"orderID": "ord3"}
        daemon.db = MagicMock()
        daemon.db.record_trade.return_value = True
        with patch("pm_bot.cli.daemon.notify", new_callable=AsyncMock):
            await daemon._execute_trade(rec)


class TestTradingDaemonRecoverState:
    def test_basic_recovery(self):
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.get_open_orders.return_value = []
        daemon.db = MagicMock()
        daemon.db.get_state_json.return_value = None
        daemon.db.get_state.return_value = "true"
        daemon._recover_state()

    def test_crash_recovery_detected(self):
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.get_open_orders.return_value = []
        daemon.db = MagicMock()
        daemon.db.get_state_json.return_value = {"some": "state"}
        daemon.db.get_state.return_value = "false"
        with patch("pm_bot.cli.daemon.asyncio.create_task"):
            daemon._recover_state()

    def test_recovery_exception(self):
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.get_open_orders.side_effect = Exception("api fail")
        daemon.db = MagicMock()
        daemon.db.get_state_json.return_value = None
        daemon.db.get_state.return_value = "true"
        daemon._recover_state()


class TestTradingDaemonPersistState:
    def test_persist(self):
        daemon = TradingDaemon({})
        daemon.db = MagicMock()
        daemon.db.get_daily_spent.return_value = 50.0
        daemon._persist_state()
        daemon.db.set_state_json.assert_called()


class TestTradingDaemonUpdateDailyState:
    def test_update(self):
        daemon = TradingDaemon({})
        daemon.db = MagicMock()
        daemon.db.get_daily_spent.return_value = 50.0
        daemon.db.get_daily_pnl.return_value = 10.0
        daemon.db.get_recent_trades.return_value = []
        daemon._update_daily_state()
        daemon.db.update_daily_state.assert_called()


class TestTradingDaemonCheckDailyReset:
    def test_already_reset_today(self):
        daemon = TradingDaemon({})
        daemon.db = MagicMock()
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daemon.db.get_state_json.return_value = {"date": today}
        daemon._check_daily_reset()

    def test_new_day_reset(self):
        daemon = TradingDaemon({})
        daemon.db = MagicMock()
        daemon.db.get_state_json.return_value = None
        daemon.db.get_daily_spent.return_value = 50.0
        daemon.db.get_daily_pnl.return_value = 10.0
        daemon.db.get_recent_trades.return_value = []
        daemon.db.get_daily_state.return_value = {
            "total_pnl": 10.0, "trade_count": 5, "win_count": 3,
        }
        with patch("pm_bot.cli.daemon.asyncio.create_task"):
            daemon._check_daily_reset()


class TestTradingDaemonGraciousShutdown:
    @pytest.mark.asyncio
    async def test_shutdown(self):
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.cancel_all_orders.return_value = {}
        daemon.db = MagicMock()
        daemon.db.get_open_trades.return_value = []
        daemon._persist_state = MagicMock()
        daemon._update_daily_state = MagicMock()
        daemon._remove_pid = MagicMock()
        with patch("pm_bot.cli.daemon.get_notifications", return_value={}):
            with patch("pm_bot.cli.daemon.send_discord", new_callable=AsyncMock):
                with patch("pm_bot.cli.daemon.send_telegram", new_callable=AsyncMock):
                    await daemon._graceful_shutdown()
        daemon.trader.stop_heartbeat.assert_called_once()
        daemon.db.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_with_pending_fills(self):
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.cancel_all_orders.return_value = {}
        daemon.trader.get_order_status.return_value = {"status": "filled"}
        daemon.db = MagicMock()
        daemon.db.get_open_trades.return_value = [{"order_id": "ord1"}]
        daemon._persist_state = MagicMock()
        daemon._update_daily_state = MagicMock()
        daemon._remove_pid = MagicMock()
        with patch("pm_bot.cli.daemon.get_notifications", return_value={}):
            with patch("pm_bot.cli.daemon.send_discord", new_callable=AsyncMock):
                with patch("pm_bot.cli.daemon.send_telegram", new_callable=AsyncMock):
                    await daemon._graceful_shutdown()
        daemon.trader.stop_heartbeat.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_cancel_failure(self):
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.cancel_all_orders.side_effect = Exception("fail")
        daemon.db = MagicMock()
        daemon.db.get_open_trades.return_value = []
        daemon._persist_state = MagicMock()
        daemon._update_daily_state = MagicMock()
        daemon._remove_pid = MagicMock()
        with patch("pm_bot.cli.daemon.get_notifications", return_value={}):
            with patch("pm_bot.cli.daemon.send_discord", new_callable=AsyncMock):
                with patch("pm_bot.cli.daemon.send_telegram", new_callable=AsyncMock):
                    await daemon._graceful_shutdown()


class TestTradingDaemonPollFills:
    @pytest.mark.asyncio
    async def test_filled_order(self):
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.get_order_status.return_value = {"status": "filled"}
        daemon.db = MagicMock()
        daemon.db.get_open_trades.return_value = [{"order_id": "ord1"}]
        await daemon._poll_fills()
        daemon.db.update_fill_status.assert_called_with("ord1", "filled")

    @pytest.mark.asyncio
    async def test_cancelled_order(self):
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.get_order_status.return_value = {"status": "cancelled"}
        daemon.db = MagicMock()
        daemon.db.get_open_trades.return_value = [{"order_id": "ord1"}]
        await daemon._poll_fills()
        daemon.db.update_fill_status.assert_called_with("ord1", "cancelled")

    @pytest.mark.asyncio
    async def test_empty_order_id(self):
        daemon = TradingDaemon({})
        daemon.db = MagicMock()
        daemon.db.get_open_trades.return_value = [{"order_id": ""}]
        await daemon._poll_fills()

    @pytest.mark.asyncio
    async def test_no_status(self):
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.get_order_status.return_value = None
        daemon.db = MagicMock()
        daemon.db.get_open_trades.return_value = [{"order_id": "ord1"}]
        await daemon._poll_fills()


class TestTradingDaemonTradeCycle:
    @pytest.mark.asyncio
    async def test_no_events(self):
        daemon = TradingDaemon({})
        daemon.trader = MagicMock()
        daemon.trader.is_configured.return_value = True
        with patch("pm_bot.cli.daemon.fetch_weather_events", new_callable=AsyncMock, return_value=[]):
            await daemon._trade_cycle()


class TestTradingDaemonWritePid:
    @patch("pm_bot.cli.daemon.PID_FILE")
    def test_write_pid(self, mock_pid):
        daemon = TradingDaemon({})
        mock_pid.parent.mkdir.return_value = None
        daemon._write_pid()
        mock_pid.write_text.assert_called()


class TestTradingDaemonSendNotification:
    @pytest.mark.asyncio
    async def test_send_notification(self):
        daemon = TradingDaemon({})
        with patch("pm_bot.cli.daemon.get_notifications", return_value={
            "discord": {"webhook_url": "http://test"},
            "telegram": {"bot_token": "tok", "chat_id": "123"},
        }):
            with patch("pm_bot.cli.daemon.send_discord", new_callable=AsyncMock) as mock_dc:
                with patch("pm_bot.cli.daemon.send_telegram", new_callable=AsyncMock) as mock_tg:
                    await daemon._send_notification("test msg", "test_event")
        mock_dc.assert_called_once()
        mock_tg.assert_called_once()


class TestTradingDaemonSendCircuitBreakerAlert:
    @pytest.mark.asyncio
    async def test_level1(self):
        from pm_bot.core.risk import RiskCheckResult
        daemon = TradingDaemon({})
        result = RiskCheckResult(allowed=True, reason="L1", kelly_adjustment=0.5, circuit_breaker_level=1)
        with patch("pm_bot.cli.daemon.get_notifications", return_value={}):
            with patch("pm_bot.cli.daemon.send_discord", new_callable=AsyncMock):
                with patch("pm_bot.cli.daemon.send_telegram", new_callable=AsyncMock):
                    await daemon.send_circuit_breaker_alert(result)

    @pytest.mark.asyncio
    async def test_level3(self):
        from pm_bot.core.risk import RiskCheckResult
        daemon = TradingDaemon({})
        result = RiskCheckResult(allowed=False, reason="L3", kelly_adjustment=0.0, circuit_breaker_level=3)
        with patch("pm_bot.cli.daemon.get_notifications", return_value={}):
            with patch("pm_bot.cli.daemon.send_discord", new_callable=AsyncMock):
                with patch("pm_bot.cli.daemon.send_telegram", new_callable=AsyncMock):
                    await daemon.send_circuit_breaker_alert(result)

    @pytest.mark.asyncio
    async def test_level2(self):
        from pm_bot.core.risk import RiskCheckResult
        daemon = TradingDaemon({})
        result = RiskCheckResult(allowed=False, reason="L2", kelly_adjustment=0.25, circuit_breaker_level=2)
        with patch("pm_bot.cli.daemon.get_notifications", return_value={}):
            with patch("pm_bot.cli.daemon.send_discord", new_callable=AsyncMock):
                with patch("pm_bot.cli.daemon.send_telegram", new_callable=AsyncMock):
                    await daemon.send_circuit_breaker_alert(result)

    @pytest.mark.asyncio
    async def test_unknown_level(self):
        from pm_bot.core.risk import RiskCheckResult
        daemon = TradingDaemon({})
        result = RiskCheckResult(allowed=True, reason="ok", kelly_adjustment=1.0, circuit_breaker_level=5)
        with patch("pm_bot.cli.daemon.get_notifications", return_value={}):
            with patch("pm_bot.cli.daemon.send_discord", new_callable=AsyncMock):
                with patch("pm_bot.cli.daemon.send_telegram", new_callable=AsyncMock):
                    await daemon.send_circuit_breaker_alert(result)


class TestDaemonStart:
    @pytest.mark.asyncio
    @patch("pm_bot.cli.daemon._is_daemon_running", return_value=True)
    async def test_already_running(self, mock_running):
        with patch("pm_bot.cli.daemon.PID_FILE") as mock_pid:
            mock_pid.read_text.return_value = "123"
            await daemon_start()

    @pytest.mark.asyncio
    @patch("pm_bot.cli.daemon._is_daemon_running", return_value=False)
    @patch("pm_bot.cli.daemon.load_config", return_value={})
    async def test_not_configured(self, mock_config, mock_running):
        await daemon_start()


class TestDaemonStop:
    @pytest.mark.asyncio
    @patch("pm_bot.cli.daemon._is_daemon_running", return_value=False)
    async def test_not_running(self, mock_running):
        await daemon_stop()

    @pytest.mark.asyncio
    @patch("pm_bot.cli.daemon._is_daemon_running", return_value=True)
    async def test_send_sigterm(self, mock_running):
        with patch("pm_bot.cli.daemon.PID_FILE") as mock_pid:
            mock_pid.read_text.return_value = "123"
            with patch("pm_bot.cli.daemon.os.kill"):
                await daemon_stop()

    @pytest.mark.asyncio
    @patch("pm_bot.cli.daemon._is_daemon_running", return_value=True)
    async def test_process_gone(self, mock_running):
        with patch("pm_bot.cli.daemon.PID_FILE") as mock_pid:
            mock_pid.read_text.return_value = "99999"
            with patch("pm_bot.cli.daemon.os.kill", side_effect=ProcessLookupError):
                mock_pid.unlink.return_value = None
                await daemon_stop()

    @pytest.mark.asyncio
    @patch("pm_bot.cli.daemon._is_daemon_running", return_value=True)
    async def test_permission_denied(self, mock_running):
        with patch("pm_bot.cli.daemon.PID_FILE") as mock_pid:
            mock_pid.read_text.return_value = "1"
            with patch("pm_bot.cli.daemon.os.kill", side_effect=PermissionError):
                await daemon_stop()


class TestDaemonStatus:
    @pytest.mark.asyncio
    @patch("pm_bot.cli.daemon._is_daemon_running", return_value=False)
    async def test_not_running(self, mock_running):
        await daemon_status()

    @pytest.mark.asyncio
    @patch("pm_bot.cli.daemon._is_daemon_running", return_value=True)
    @patch("pm_bot.cli.daemon.TradeDB")
    async def test_running(self, mock_db_cls, mock_running):
        mock_db = MagicMock()
        mock_db.get_daily_spent.return_value = 50.0
        mock_db.get_daily_pnl.return_value = 10.0
        mock_db.get_open_trades.return_value = []
        mock_db.get_total_exposure.return_value = 100.0
        mock_db_cls.return_value = mock_db
        with patch("pm_bot.cli.daemon.PID_FILE") as mock_pid:
            mock_pid.read_text.return_value = "123"
            with patch("pm_bot.cli.daemon.HEARTBEAT_FILE") as mock_hb:
                mock_hb.exists.return_value = False
                await daemon_status()

    @pytest.mark.asyncio
    @patch("pm_bot.cli.daemon._is_daemon_running", return_value=True)
    @patch("pm_bot.cli.daemon.TradeDB")
    async def test_with_heartbeat(self, mock_db_cls, mock_running):
        mock_db = MagicMock()
        mock_db.get_daily_spent.return_value = 50.0
        mock_db.get_daily_pnl.return_value = 10.0
        mock_db.get_open_trades.return_value = []
        mock_db.get_total_exposure.return_value = 100.0
        mock_db_cls.return_value = mock_db
        hb_data = json.dumps({"ts": time.time(), "uptime": 3600, "cycle": 5, "bankroll": 500.0})
        with patch("pm_bot.cli.daemon.PID_FILE") as mock_pid:
            mock_pid.read_text.return_value = "123"
            with patch("pm_bot.cli.daemon.HEARTBEAT_FILE") as mock_hb:
                mock_hb.exists.return_value = True
                mock_hb.read_text.return_value = hb_data
                await daemon_status()

    @pytest.mark.asyncio
    @patch("pm_bot.cli.daemon._is_daemon_running", return_value=True)
    @patch("pm_bot.cli.daemon.TradeDB")
    async def test_db_exception(self, mock_db_cls, mock_running):
        mock_db = MagicMock()
        mock_db.get_daily_spent.side_effect = Exception("db error")
        mock_db_cls.return_value = mock_db
        with patch("pm_bot.cli.daemon.PID_FILE") as mock_pid:
            mock_pid.read_text.return_value = "123"
            with patch("pm_bot.cli.daemon.HEARTBEAT_FILE") as mock_hb:
                mock_hb.exists.return_value = False
                await daemon_status()

    @pytest.mark.asyncio
    @patch("pm_bot.cli.daemon._is_daemon_running", return_value=True)
    @patch("pm_bot.cli.daemon.TradeDB")
    async def test_invalid_heartbeat_json(self, mock_db_cls, mock_running):
        mock_db = MagicMock()
        mock_db.get_daily_spent.return_value = 50.0
        mock_db.get_daily_pnl.return_value = 10.0
        mock_db.get_open_trades.return_value = []
        mock_db.get_total_exposure.return_value = 100.0
        mock_db_cls.return_value = mock_db
        with patch("pm_bot.cli.daemon.PID_FILE") as mock_pid:
            mock_pid.read_text.return_value = "123"
            with patch("pm_bot.cli.daemon.HEARTBEAT_FILE") as mock_hb:
                mock_hb.exists.return_value = True
                mock_hb.read_text.return_value = "invalid json{{{"
                await daemon_status()


class TestFetchForecastAt:
    @pytest.mark.asyncio
    async def test_http_error(self):
        import httpx
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.HTTPError("fail")
        result = await _fetch_forecast_at(mock_client, 40.0, -74.0, "NYC")
        assert result is None

    @pytest.mark.asyncio
    async def test_successful(self):
        mock_client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = {
            "daily": {"temperature_2m_max": [25.0]},
        }
        resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=resp)
        result = await _fetch_forecast_at(mock_client, 40.0, -74.0, "NYC")
        assert result is not None
        assert result.temp_high_c == 25.0
