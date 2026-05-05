from __future__ import annotations

from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta

from pm_bot.core.risk import RiskManager, RiskCheckResult
from pm_bot.core.db import TradeDB


def _mock_db():
    db = MagicMock(spec=TradeDB)
    db.get_daily_pnl.return_value = 0.0
    db.get_daily_spent.return_value = 0.0
    db.get_city_spent.return_value = 0.0
    db.get_total_exposure.return_value = 0.0
    db.get_consecutive_losses.return_value = 0
    db.get_state.return_value = None
    return db


class TestRiskCheckResult:
    def test_defaults(self):
        r = RiskCheckResult(allowed=True)
        assert r.allowed is True
        assert r.reason == ""
        assert r.kelly_adjustment == 1.0
        assert r.circuit_breaker_level == 0


class TestCircuitBreaker:
    def test_no_loss(self):
        db = _mock_db()
        rm = RiskManager(db=db, bankroll=500.0)
        result = rm.check_circuit_breaker()
        assert result.allowed is True
        assert result.kelly_adjustment == 1.0

    def test_l1_loss(self):
        db = _mock_db()
        db.get_daily_pnl.return_value = -30.0
        rm = RiskManager(db=db, bankroll=500.0, circuit_breaker_l1=0.05)
        result = rm.check_circuit_breaker()
        assert result.allowed is True
        assert result.kelly_adjustment == 0.5
        assert result.circuit_breaker_level == 1

    def test_l2_loss(self):
        db = _mock_db()
        db.get_daily_pnl.return_value = -60.0
        rm = RiskManager(db=db, bankroll=500.0, circuit_breaker_l2=0.10)
        result = rm.check_circuit_breaker()
        assert result.allowed is True
        assert result.kelly_adjustment == 0.25
        assert result.circuit_breaker_level == 2

    def test_l3_loss(self):
        db = _mock_db()
        db.get_daily_pnl.return_value = -100.0
        rm = RiskManager(db=db, bankroll=500.0, circuit_breaker_l3=0.15)
        result = rm.check_circuit_breaker()
        assert result.allowed is False
        assert result.kelly_adjustment == 0.0
        assert result.circuit_breaker_level == 3


class TestConsecutiveLosses:
    def test_no_losses(self):
        db = _mock_db()
        db.get_consecutive_losses.return_value = 0
        rm = RiskManager(db=db)
        result = rm.check_consecutive_losses()
        assert result.allowed is True

    def test_few_losses(self):
        db = _mock_db()
        db.get_consecutive_losses.return_value = 3
        rm = RiskManager(db=db, consecutive_loss_pause_count=5)
        result = rm.check_consecutive_losses()
        assert result.allowed is True

    def test_too_many_losses(self):
        db = _mock_db()
        db.get_consecutive_losses.return_value = 5
        db.get_state.return_value = None
        rm = RiskManager(db=db, consecutive_loss_pause_count=5, consecutive_loss_pause_minutes=60)
        result = rm.check_consecutive_losses()
        assert result.allowed is False
        assert "Consecutive" in result.reason

    def test_already_paused(self):
        db = _mock_db()
        db.get_consecutive_losses.return_value = 5
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        db.get_state.return_value = future
        rm = RiskManager(db=db, consecutive_loss_pause_count=5)
        result = rm.check_consecutive_losses()
        assert result.allowed is False

    def test_pause_expired(self):
        db = _mock_db()
        db.get_consecutive_losses.return_value = 5
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db.get_state.return_value = past
        rm = RiskManager(db=db, consecutive_loss_pause_count=5, consecutive_loss_pause_minutes=60)
        result = rm.check_consecutive_losses()
        assert result.allowed is False


class TestCheckSpread:
    def test_narrow_spread(self):
        db = _mock_db()
        rm = RiskManager(db=db, max_spread=0.10)
        result = rm.check_spread(0.50, 0.50)
        assert result.allowed is True

    def test_wide_spread(self):
        db = _mock_db()
        rm = RiskManager(db=db, max_spread=0.10)
        result = rm.check_spread(0.70, 0.50)
        assert result.allowed is False
        assert "Spread" in result.reason

    def test_exact_limit(self):
        db = _mock_db()
        rm = RiskManager(db=db, max_spread=0.10)
        result = rm.check_spread(0.55, 0.55)
        assert result.allowed is False


class TestCheckTimeRisk:
    def test_enough_time(self):
        db = _mock_db()
        rm = RiskManager(db=db, no_new_before_resolution_h=6)
        result = rm.check_time_risk(hours_to_resolution=12.0)
        assert result.allowed is True

    def test_too_close(self):
        db = _mock_db()
        rm = RiskManager(db=db, no_new_before_resolution_h=6)
        result = rm.check_time_risk(hours_to_resolution=3.0)
        assert result.allowed is False
        assert "Too close" in result.reason

    def test_none_hours(self):
        db = _mock_db()
        rm = RiskManager(db=db, no_new_before_resolution_h=6)
        result = rm.check_time_risk(hours_to_resolution=None)
        assert result.allowed is True


class TestCheckDailyLimit:
    def test_within_limit(self):
        db = _mock_db()
        db.get_daily_spent.return_value = 50.0
        rm = RiskManager(db=db, max_daily=200.0)
        result = rm.check_daily_limit(50.0)
        assert result.allowed is True

    def test_exceeds_limit(self):
        db = _mock_db()
        db.get_daily_spent.return_value = 190.0
        rm = RiskManager(db=db, max_daily=200.0)
        result = rm.check_daily_limit(50.0)
        assert result.allowed is False


class TestCheckCityLimit:
    def test_within_limit(self):
        db = _mock_db()
        db.get_city_spent.return_value = 50.0
        rm = RiskManager(db=db, max_per_city=100.0)
        result = rm.check_city_limit("NYC", 30.0)
        assert result.allowed is True

    def test_exceeds_limit(self):
        db = _mock_db()
        db.get_city_spent.return_value = 90.0
        rm = RiskManager(db=db, max_per_city=100.0)
        result = rm.check_city_limit("NYC", 30.0)
        assert result.allowed is False


class TestCheckTotalExposure:
    def test_within_limit(self):
        db = _mock_db()
        db.get_total_exposure.return_value = 100.0
        rm = RiskManager(db=db, bankroll=500.0, max_total_pct=0.30)
        result = rm.check_total_exposure(30.0)
        assert result.allowed is True

    def test_exceeds_limit(self):
        db = _mock_db()
        db.get_total_exposure.return_value = 145.0
        rm = RiskManager(db=db, bankroll=500.0, max_total_pct=0.30)
        result = rm.check_total_exposure(10.0)
        assert result.allowed is False


class TestFullCheck:
    def test_all_pass(self):
        db = _mock_db()
        rm = RiskManager(db=db, bankroll=500.0, max_spread=0.10, max_daily=200.0,
                         max_per_city=100.0, max_total_pct=0.30)
        result = rm.full_check(city="NYC", amount_usd=50.0, yes_price=0.50, no_price=0.50,
                               hours_to_resolution=12.0)
        assert result.allowed is True

    def test_fails_on_spread(self):
        db = _mock_db()
        rm = RiskManager(db=db, bankroll=500.0, max_spread=0.05, max_daily=200.0,
                         max_per_city=100.0, max_total_pct=0.30)
        result = rm.full_check(city="NYC", amount_usd=50.0, yes_price=0.70, no_price=0.50,
                               hours_to_resolution=12.0)
        assert result.allowed is False

    def test_fails_on_time(self):
        db = _mock_db()
        rm = RiskManager(db=db, bankroll=500.0, max_spread=0.10, max_daily=200.0,
                         max_per_city=100.0, max_total_pct=0.30, no_new_before_resolution_h=6)
        result = rm.full_check(city="NYC", amount_usd=50.0, yes_price=0.50, no_price=0.50,
                               hours_to_resolution=3.0)
        assert result.allowed is False

    def test_kelly_adjusted_on_l1(self):
        db = _mock_db()
        db.get_daily_pnl.return_value = -30.0
        rm = RiskManager(db=db, bankroll=500.0, max_spread=0.10, max_daily=200.0,
                         max_per_city=100.0, max_total_pct=0.30, circuit_breaker_l1=0.05)
        result = rm.full_check(city="NYC", amount_usd=50.0, yes_price=0.50, no_price=0.50,
                               hours_to_resolution=12.0)
        assert result.allowed is True
        assert result.kelly_adjustment == 0.5


class TestDailyLossPct:
    def test_no_loss(self):
        db = _mock_db()
        db.get_daily_pnl.return_value = 10.0
        rm = RiskManager(db=db, bankroll=500.0)
        assert rm.daily_loss_pct() == 0.0

    def test_with_loss(self):
        db = _mock_db()
        db.get_daily_pnl.return_value = -30.0
        rm = RiskManager(db=db, bankroll=500.0)
        assert abs(rm.daily_loss_pct() - 0.06) < 0.01
