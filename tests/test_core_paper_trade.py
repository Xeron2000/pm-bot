from __future__ import annotations

import sqlite3

from pm_bot.core.paper_trade import PaperTradeDB


def test_record_trade_persists_fill_probability(tmp_path):
    db = PaperTradeDB(tmp_path / "paper.db", initial_bankroll=100.0)

    assert db.record_trade(
        order_id="ord-1",
        market_id="m1",
        side="YES",
        price=0.25,
        size_usd=10.0,
        shares=40.0,
        strategy="gopfan2",
        edge=0.12,
        fill_probability=0.7,
    )

    trade = db.get_open_trades()[0]
    assert trade["fill_probability"] == 0.7
    assert db.get_total_exposure() == 10.0


def test_record_unfilled_trade_does_not_count_exposure_or_daily_spend(tmp_path):
    db = PaperTradeDB(tmp_path / "paper.db", initial_bankroll=100.0)

    assert db.record_trade(
        order_id="ord-unfilled",
        market_id="m-unfilled",
        side="YES",
        price=0.02,
        size_usd=10.0,
        shares=0.0,
        strategy="gopfan2",
        edge=0.12,
        fill_probability=0.0,
        status="unfilled",
        fill_reason="deterministic_fill_model",
    )

    recent = db.get_recent_trades()[0]
    assert recent["status"] == "unfilled"
    assert recent["fill_reason"] == "deterministic_fill_model"
    assert db.get_open_trades() == []
    assert db.get_total_exposure() == 0.0
    assert db.daily_spent == 0.0


def test_duplicate_order_does_not_increment_daily_spent(tmp_path):
    db = PaperTradeDB(tmp_path / "paper.db", initial_bankroll=100.0)
    kwargs = dict(
        order_id="ord-dupe",
        market_id="m-dupe",
        side="YES",
        price=0.25,
        size_usd=10.0,
        shares=40.0,
        strategy="gopfan2",
        edge=0.12,
    )

    assert db.record_trade(**kwargs)
    assert not db.record_trade(**kwargs)

    assert db.daily_spent == 10.0
    assert len(db.get_recent_trades()) == 1


def test_close_yes_trade_at_stop_loss_price(tmp_path):
    db = PaperTradeDB(tmp_path / "paper.db", initial_bankroll=100.0)
    db.record_trade(
        order_id="ord-yes",
        market_id="m1",
        side="YES",
        price=0.50,
        size_usd=10.0,
        shares=20.0,
        strategy="gopfan2",
        edge=0.12,
    )

    pnl = db.close_trade_at_price("ord-yes", exit_price=0.35, reason="stop_loss_20%")

    assert pnl == -3.0
    assert db.bankroll == 97.0
    assert db.get_total_exposure() == 0.0
    stats = db.get_trade_stats()
    assert stats["total_settled"] == 1
    assert stats["losses"] == 1


def test_close_no_trade_uses_no_token_price(tmp_path):
    db = PaperTradeDB(tmp_path / "paper.db", initial_bankroll=100.0)
    db.record_trade(
        order_id="ord-no",
        market_id="m2",
        side="NO",
        price=0.40,
        size_usd=10.0,
        shares=25.0,
        strategy="neg_risk_sum",
        edge=0.10,
    )

    pnl = db.close_trade_at_price("ord-no", exit_price=0.30, reason="stop_loss_20%")

    assert pnl == -2.5
    assert db.bankroll == 97.5


def test_settle_no_position_pnl_is_symmetric_with_yes(tmp_path):
    db = PaperTradeDB(tmp_path / "paper.db", initial_bankroll=100.0)
    db.record_trade(
        order_id="ord-no-win",
        market_id="m3",
        side="NO",
        price=0.40,
        size_usd=10.0,
        shares=25.0,
        strategy="neg_risk_sum",
        edge=0.10,
    )

    pnl = db.settle_market("m3", winning_side="NO")

    assert pnl == 15.0
    assert db.bankroll == 115.0


def test_settle_by_temperature_respects_bucket_hit(tmp_path):
    db = PaperTradeDB(tmp_path / "paper.db", initial_bankroll=100.0)
    db.record_trade(
        order_id="ord-temp-hit",
        market_id="m-temp-hit",
        side="YES",
        price=0.25,
        size_usd=10.0,
        shares=40.0,
        strategy="gopfan2",
        edge=0.12,
        temp_label="23°C",
    )

    pnl = db.settle_by_temperature("m-temp-hit", observed_temp_c=23.8)

    assert pnl == 30.0
    assert db.bankroll == 130.0


def test_settle_by_temperature_settles_no_when_bucket_misses(tmp_path):
    db = PaperTradeDB(tmp_path / "paper.db", initial_bankroll=100.0)
    db.record_trade(
        order_id="ord-temp-miss",
        market_id="m-temp-miss",
        side="NO",
        price=0.75,
        size_usd=10.0,
        shares=13.3333333333,
        strategy="neg_risk_sum",
        edge=0.12,
        temp_label="23°C",
    )

    pnl = db.settle_by_temperature("m-temp-miss", observed_temp_c=24.1)

    assert round(pnl, 6) == round(3.3333333333, 6)
    assert round(db.bankroll, 6) == round(103.3333333333, 6)


def test_migrates_existing_v1_database(tmp_path):
    path = tmp_path / "paper.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')));
        INSERT INTO schema_version (version) VALUES (1);
        CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE,
            market_id TEXT NOT NULL,
            strategy TEXT NOT NULL,
            side TEXT NOT NULL,
            price REAL NOT NULL,
            size_usd REAL NOT NULL,
            shares REAL NOT NULL,
            kelly_fraction REAL,
            edge REAL,
            city TEXT,
            temp_label TEXT,
            reasoning TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            settled_pnl REAL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            settled_at TEXT
        );
        CREATE TABLE paper_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE paper_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE,
            starting_bankroll REAL NOT NULL,
            ending_bankroll REAL NOT NULL,
            trade_count INTEGER NOT NULL DEFAULT 0,
            win_count INTEGER NOT NULL DEFAULT 0,
            loss_count INTEGER NOT NULL DEFAULT 0,
            total_pnl REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.commit()
    conn.close()

    db = PaperTradeDB(path, initial_bankroll=100.0)

    db.record_trade(
        order_id="ord-migrated",
        market_id="m4",
        side="YES",
        price=0.20,
        size_usd=5.0,
        shares=25.0,
        strategy="gopfan2",
        edge=0.20,
        fill_probability=0.1,
    )
    assert db.get_open_trades()[0]["fill_probability"] == 0.1
