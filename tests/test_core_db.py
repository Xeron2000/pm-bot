from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pm_bot.core.db import TradeDB, _utc_now, _utc_today, SCHEMA_V1


class TestTradeDBInit:
    def test_creates_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "subdir" / "test.db"
            db = TradeDB(db_path=db_path)
            conn = db._get_conn()
            assert conn is not None
            db.close()

    def test_migration_applied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            conn = db._get_conn()
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            table_names = {t[0] for t in tables}
            assert "trades" in table_names
            assert "positions" in table_names
            assert "daily_state" in table_names
            assert "daemon_state" in table_names
            assert "schema_version" in table_names
            db.close()

    def test_close_clears_conn(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db._get_conn()
            db.close()
            assert db._conn is None


class TestTradeDBRecordTrade:
    def test_record_and_retrieve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            result = db.record_trade(
                order_id="ord1", market_id="m1", side="YES",
                price=0.5, amount_usd=10.0, strategy="test",
                edge=0.05, city="NYC", temp_label="25°C",
            )
            assert result is True
            trades = db.get_recent_trades(10)
            assert len(trades) == 1
            assert trades[0]["order_id"] == "ord1"
            db.close()

    def test_duplicate_via_integrity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db.record_trade(order_id="ord1", market_id="m1", side="YES",
                          price=0.5, amount_usd=10.0, strategy="test", edge=0.05)
            trades = db.get_recent_trades(10)
            assert len(trades) == 1
            db.close()


class TestTradeDBUpdateFillStatus:
    def test_filled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db.record_trade(order_id="ord1", market_id="m1", side="YES",
                          price=0.5, amount_usd=10.0, strategy="test", edge=0.05)
            db.update_fill_status("ord1", "filled")
            trades = db.get_recent_trades(10)
            assert trades[0]["fill_status"] == "filled"
            assert trades[0]["filled_at"] is not None
            db.close()

    def test_cancelled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db.record_trade(order_id="ord1", market_id="m1", side="YES",
                          price=0.5, amount_usd=10.0, strategy="test", edge=0.05)
            db.update_fill_status("ord1", "cancelled")
            trades = db.get_recent_trades(10)
            assert trades[0]["fill_status"] == "cancelled"
            assert trades[0]["cancelled_at"] is not None
            db.close()

    def test_partial(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db.record_trade(order_id="ord1", market_id="m1", side="YES",
                          price=0.5, amount_usd=10.0, strategy="test", edge=0.05)
            db.update_fill_status("ord1", "partial")
            trades = db.get_recent_trades(10)
            assert trades[0]["fill_status"] == "partial"
            db.close()


class TestTradeDBGetDailySpent:
    def test_no_trades(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            assert db.get_daily_spent() == 0.0
            db.close()

    def test_with_trades(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db.record_trade(order_id="ord1", market_id="m1", side="YES",
                          price=0.5, amount_usd=10.0, strategy="test", edge=0.05)
            assert db.get_daily_spent() == 10.0
            db.close()


class TestTradeDBGetCitySpent:
    def test_with_city(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db.record_trade(order_id="ord1", market_id="m1", side="YES",
                          price=0.5, amount_usd=10.0, strategy="test",
                          edge=0.05, city="NYC")
            assert db.get_city_spent("NYC") == 10.0
            assert db.get_city_spent("London") == 0.0
            db.close()


class TestTradeDBGetTotalExposure:
    def test_with_open_trades(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db.record_trade(order_id="ord1", market_id="m1", side="YES",
                          price=0.5, amount_usd=10.0, strategy="test", edge=0.05)
            assert db.get_total_exposure() == 10.0
            db.close()


class TestTradeDBGetOpenTrades:
    def test_only_open(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db.record_trade(order_id="ord1", market_id="m1", side="YES",
                          price=0.5, amount_usd=10.0, strategy="test", edge=0.05)
            db.record_trade(order_id="ord2", market_id="m2", side="YES",
                          price=0.3, amount_usd=5.0, strategy="test", edge=0.03)
            db.update_fill_status("ord2", "filled")
            open_trades = db.get_open_trades()
            assert len(open_trades) == 1
            assert open_trades[0]["order_id"] == "ord1"
            db.close()


class TestTradeDBDailyState:
    def test_get_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            state = db.get_daily_state("2026-01-01")
            assert state["total_spent"] == 0.0
            assert state["date"] == "2026-01-01"
            db.close()

    def test_update_and_get(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db.update_daily_state("2026-01-01", total_spent=50.0, total_pnl=10.0)
            state = db.get_daily_state("2026-01-01")
            assert state["total_spent"] == 50.0
            assert state["total_pnl"] == 10.0
            db.close()

    def test_update_creates_new(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db.update_daily_state("2026-01-01", total_spent=50.0)
            state = db.get_daily_state("2026-01-01")
            assert state["total_spent"] == 50.0
            db.close()


class TestTradeDBDaemonState:
    def test_set_and_get(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db.set_state("key1", "value1")
            assert db.get_state("key1") == "value1"
            assert db.get_state("missing") is None
            db.close()

    def test_json_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db.set_state_json("config", {"alpha": 0.15})
            result = db.get_state_json("config")
            assert result == {"alpha": 0.15}
            db.close()

    def test_json_state_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            assert db.get_state_json("missing") is None
            db.close()


class TestTradeDBConsecutiveLosses:
    def test_no_losses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            assert db.get_consecutive_losses() == 0
            db.close()

    def test_with_winning_day(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db.update_daily_state("2026-01-01", total_pnl=10.0, trade_count=5)
            assert db.get_consecutive_losses() == 0
            db.close()

    def test_with_losing_days(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db.update_daily_state("2026-01-02", total_pnl=-5.0, trade_count=3)
            db.update_daily_state("2026-01-01", total_pnl=-3.0, trade_count=2)
            assert db.get_consecutive_losses() == 2
            db.close()


class TestTradeDBDuplicateCheck:
    def test_no_duplicate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            assert db.check_duplicate_order("m1", "YES") is False
            db.close()

    def test_with_duplicate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db.record_trade(order_id="ord1", market_id="m1", side="YES",
                          price=0.5, amount_usd=10.0, strategy="test", edge=0.05)
            assert db.check_duplicate_order("m1", "YES") is True
            db.close()


class TestTradeDBReconcile:
    def test_reconcile_fills(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = TradeDB(db_path=db_path)
            db.record_trade(order_id="ord1", market_id="m1", side="YES",
                          price=0.5, amount_usd=10.0, strategy="test", edge=0.05)
            db.record_trade(order_id="ord2", market_id="m2", side="YES",
                          price=0.3, amount_usd=5.0, strategy="test", edge=0.03)
            db.reconcile_open_orders({"ord1"})
            trades = db.get_recent_trades(10)
            ord1 = [t for t in trades if t["order_id"] == "ord1"][0]
            ord2 = [t for t in trades if t["order_id"] == "ord2"][0]
            assert ord1["fill_status"] == "open"
            assert ord2["fill_status"] == "filled"
            db.close()


class TestHelperFunctions:
    def test_utc_now_format(self):
        now = _utc_now()
        parsed = datetime.strptime(now, "%Y-%m-%d %H:%M:%S")
        assert parsed is not None

    def test_utc_today_format(self):
        today = _utc_today()
        assert len(today) == 10
        assert "-" in today
