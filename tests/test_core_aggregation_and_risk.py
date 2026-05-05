from __future__ import annotations

import tempfile
from pathlib import Path

from pm_bot.core.aggregation import (
    compute_bma_weights,
    compute_consensus_probability,
    compute_agreement_score,
    bucket_probability_normal,
)
from pm_bot.core.db import TradeDB
from pm_bot.core.risk import RiskManager, RiskCheckResult
from pm_bot.models.forecast import SourceForecast


class TestNormCdf:
    def test_bucket_probability_normal(self):
        p = bucket_probability_normal(25.0, 2.0, 25.0, 25.0, "C")
        assert 0 < p < 1

    def test_zero_std(self):
        p = bucket_probability_normal(25.0, 0.0, 25.0, 25.0, "C")
        assert p > 0

    def test_fahrenheit(self):
        p = bucket_probability_normal(33.0, 2.0, 90.0, 92.0, "F")
        assert 0 <= p <= 1


class TestComputeBmaWeights:
    def test_single_source(self):
        sources = [SourceForecast(source="nws", temp_high_c=25.0, std_c=2.0)]
        weights = compute_bma_weights(sources)
        assert len(weights) == 1
        assert abs(weights[0] - 1.0) < 0.01

    def test_two_sources(self):
        sources = [
            SourceForecast(source="nws", temp_high_c=25.0, std_c=2.0),
            SourceForecast(source="gfs", temp_high_c=27.0, std_c=4.0),
        ]
        weights = compute_bma_weights(sources)
        assert len(weights) == 2
        assert abs(sum(weights) - 1.0) < 0.01
        assert weights[0] > weights[1]

    def test_empty(self):
        assert compute_bma_weights([]) == []


class TestComputeConsensusProbability:
    def test_two_sources(self):
        sources = [
            SourceForecast(source="nws", temp_high_c=25.0, std_c=2.0),
            SourceForecast(source="gfs", temp_high_c=27.0, std_c=2.0),
        ]
        prob = compute_consensus_probability(sources, 25.0, 25.0, "C")
        assert 0 <= prob <= 1

    def test_empty(self):
        prob = compute_consensus_probability([], 25.0, 25.0, "C")
        assert prob == 0.5


class TestComputeAgreementScore:
    def test_perfect_agreement(self):
        sources = [
            SourceForecast(source="nws", temp_high_c=25.0, std_c=2.0),
            SourceForecast(source="gfs", temp_high_c=25.0, std_c=2.0),
        ]
        score = compute_agreement_score(sources)
        assert score == 1.0

    def test_wide_disagreement(self):
        sources = [
            SourceForecast(source="nws", temp_high_c=20.0, std_c=2.0),
            SourceForecast(source="gfs", temp_high_c=30.0, std_c=2.0),
        ]
        score = compute_agreement_score(sources)
        assert score < 1.0

    def test_single_source(self):
        sources = [SourceForecast(source="nws", temp_high_c=25.0, std_c=2.0)]
        score = compute_agreement_score(sources)
        assert score == 0.5


class TestRiskCheckResult:
    def test_defaults(self):
        r = RiskCheckResult(allowed=True)
        assert r.allowed is True
        assert r.reason == ""
        assert r.kelly_adjustment == 1.0
        assert r.circuit_breaker_level == 0

    def test_blocked(self):
        r = RiskCheckResult(allowed=False, reason="too risky", kelly_adjustment=0.0)
        assert r.allowed is False
        assert r.kelly_adjustment == 0.0


class TestRiskManagerCircuitBreaker:
    def test_no_loss(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            rm = RiskManager(db=db, bankroll=500.0)
            result = rm.check_circuit_breaker()
            assert result.allowed is True
            assert result.kelly_adjustment == 1.0
            db.close()

    def test_l1_loss(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            from pm_bot.core.db import _utc_today
            today = _utc_today()
            conn = db._get_conn()
            conn.execute("INSERT INTO daily_state (date, total_pnl, trade_count) VALUES (?, -30.0, 5)", (today,))
            conn.commit()
            rm = RiskManager(db=db, bankroll=500.0, circuit_breaker_l1=0.05)
            result = rm.check_circuit_breaker()
            assert result.kelly_adjustment == 0.5
            db.close()

    def test_l2_loss(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            from pm_bot.core.db import _utc_today
            today = _utc_today()
            conn = db._get_conn()
            conn.execute("INSERT INTO daily_state (date, total_pnl, trade_count) VALUES (?, -60.0, 5)", (today,))
            conn.commit()
            rm = RiskManager(db=db, bankroll=500.0, circuit_breaker_l2=0.10)
            result = rm.check_circuit_breaker()
            assert result.kelly_adjustment == 0.25
            db.close()

    def test_l3_loss(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            from pm_bot.core.db import _utc_today
            today = _utc_today()
            conn = db._get_conn()
            conn.execute("INSERT INTO daily_state (date, total_pnl, trade_count) VALUES (?, -100.0, 5)", (today,))
            conn.commit()
            rm = RiskManager(db=db, bankroll=500.0, circuit_breaker_l3=0.15)
            result = rm.check_circuit_breaker()
            assert result.allowed is False
            assert result.kelly_adjustment == 0.0
            db.close()


class TestRiskManagerSpreadCheck:
    def test_normal_spread(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            rm = RiskManager(db=db)
            result = rm.check_spread(0.50, 0.50)
            assert result.allowed is True

    def test_wide_spread(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            rm = RiskManager(db=db, max_spread=0.05)
            result = rm.check_spread(0.55, 0.55)
            assert result.allowed is False


class TestRiskManagerTimeCheck:
    def test_far_from_resolution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            rm = RiskManager(db=db)
            result = rm.check_time_risk(hours_to_resolution=24.0)
            assert result.allowed is True

    def test_too_close(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            rm = RiskManager(db=db, no_new_before_resolution_h=6)
            result = rm.check_time_risk(hours_to_resolution=3.0)
            assert result.allowed is False

    def test_none_hours(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            rm = RiskManager(db=db)
            result = rm.check_time_risk()
            assert result.allowed is True


class TestRiskManagerDailyLimit:
    def test_within_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            rm = RiskManager(db=db, max_daily=200.0)
            result = rm.check_daily_limit(50.0)
            assert result.allowed is True

    def test_exceeds_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            rm = RiskManager(db=db, max_daily=10.0)
            result = rm.check_daily_limit(50.0)
            assert result.allowed is False


class TestRiskManagerCityLimit:
    def test_within_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            rm = RiskManager(db=db, max_per_city=100.0)
            result = rm.check_city_limit("NYC", 10.0)
            assert result.allowed is True

    def test_exceeds_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            rm = RiskManager(db=db, max_per_city=5.0)
            result = rm.check_city_limit("NYC", 10.0)
            assert result.allowed is False


class TestRiskManagerTotalExposure:
    def test_within_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            rm = RiskManager(db=db, bankroll=500.0, max_total_pct=0.30)
            result = rm.check_total_exposure(50.0)
            assert result.allowed is True

    def test_exceeds_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            rm = RiskManager(db=db, bankroll=100.0, max_total_pct=0.10)
            result = rm.check_total_exposure(50.0)
            assert result.allowed is False


class TestRiskManagerFullCheck:
    def test_all_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            rm = RiskManager(db=db, bankroll=500.0)
            result = rm.full_check("NYC", 10.0, 0.50, 0.50)
            assert result.allowed is True

    def test_spread_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            rm = RiskManager(db=db, bankroll=500.0, max_spread=0.05)
            result = rm.full_check("NYC", 10.0, 0.55, 0.55)
            assert result.allowed is False


class TestRiskManagerDailyLossPct:
    def test_no_loss(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TradeDB(db_path=Path(tmpdir) / "test.db")
            rm = RiskManager(db=db, bankroll=500.0)
            assert rm.daily_loss_pct() == 0.0
