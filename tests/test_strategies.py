from __future__ import annotations

from pm_bot.strategies.base import Strategy, ALL_STRATEGIES, Gopfan2Strategy
from pm_bot.models.market import (
    TemperatureBucket,
    WeatherEvent,
    ForecastResult,
)


def _make_event(buckets, city="New York", measure_type="high"):
    return WeatherEvent(
        event_id="test_ev",
        title=f"High temp in {city}",
        slug=f"{city}-2026-01-15",
        city=city,
        date="2026-01-15",
        measure_type=measure_type,
        buckets=buckets,
    )


def _make_bucket(temp_low, temp_high, temp_unit="C", yes_price=0.2, market_id="b1"):
    return TemperatureBucket(
        market_id=market_id,
        question=f"{temp_low}\u00b0C",
        temp_low=float(temp_low),
        temp_high=float(temp_high),
        temp_unit=temp_unit,
        yes_price=yes_price,
        no_price=1.0 - yes_price,
        volume=500.0,
    )


def _make_forecast(temp_high_c=25.0, city="New York", std=None, members=None):
    if members is None:
        spread = std or 2.0
        members = [temp_high_c + i * spread / 4 for i in range(-2, 3)]
    return ForecastResult(
        city=city,
        date="2026-01-15",
        model="gfs",
        temp_high_c=temp_high_c,
        measure_type="high",
        members=members,
    )


class TestStrategyRegistry:
    def test_all_strategies_registered(self):
        """All active strategies are registered."""
        expected = ["gopfan2", "laddering", "tail_no_barbell", "forecast_arb", "resolution_delay", "near_certain_bond"]
        assert list(ALL_STRATEGIES.keys()) == expected

    def test_registry_instances(self):
        assert isinstance(ALL_STRATEGIES["gopfan2"], Gopfan2Strategy)

    def test_no_deleted_strategies(self):
        deleted = [
            "narrow_no",
            "sum_arb",
            "metar_obs",
            "metar_lock",
            "mean_reversion",
            "neg_risk_field_fade",
            "neg_risk_sum",
            "truncation_edge",
            "ensemble_spread",
            "resolution_div",
        ]
        for name in deleted:
            assert name not in ALL_STRATEGIES


class TestStrategyBase:
    def test_supports_backtest_property(self):
        s = Strategy()
        assert s.supports_backtest is True

    def test_strategy_run_returns_list(self):
        s = Strategy()
        result = s.run(_make_event([]))
        assert isinstance(result, list)


class TestGopfan2Strategy:
    def test_tail_low_signal(self):
        buckets = [
            _make_bucket(-999, 20, yes_price=0.03, market_id="tail_low"),
            _make_bucket(20, 20, yes_price=0.10, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.25, market_id="b21"),
            _make_bucket(22, 22, yes_price=0.30, market_id="b22"),
            _make_bucket(23, 23, yes_price=0.20, market_id="b23"),
            _make_bucket(999, 999, yes_price=0.07, market_id="tail_high"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=19.5)
        strategy = Gopfan2Strategy()
        recs = strategy.run(event, forecast=forecast)
        yes_recs = [r for r in recs if r.direction == "YES" and r.price <= 0.15]
        assert len(yes_recs) > 0
        assert all(r.edge > 0 for r in yes_recs)
        for r in yes_recs:
            assert "model=" in r.reasoning

    def test_no_signal_when_center_close(self):
        buckets = [_make_bucket(i, i, yes_price=0.20, market_id=f"b{i}") for i in range(20, 30)]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=25.0)
        strategy = Gopfan2Strategy()
        recs = strategy.run(event, forecast=forecast)
        assert all(r.edge > 0 for r in recs)

    def test_only_tail_buckets(self):
        """gopfan2 should only trade buckets with yes_price <= 0.15."""
        buckets = [
            _make_bucket(-999, 20, yes_price=0.03, market_id="tail_low"),
            _make_bucket(21, 21, yes_price=0.10, market_id="b21"),
            _make_bucket(22, 22, yes_price=0.20, market_id="b22"),
            _make_bucket(23, 23, yes_price=0.30, market_id="b23"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=21.0)
        strategy = Gopfan2Strategy()
        recs = strategy.run(event, forecast=forecast)
        for r in recs:
            assert r.bucket.yes_price <= 0.15, f"Should not trade bucket with yes_price={r.bucket.yes_price}"

    def test_no_no_direction(self):
        """gopfan2 should only generate YES recommendations."""
        buckets = [
            _make_bucket(-999, 20, yes_price=0.03, market_id="tail_low"),
            _make_bucket(999, 999, yes_price=0.05, market_id="tail_high"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=25.0)
        strategy = Gopfan2Strategy()
        recs = strategy.run(event, forecast=forecast)
        for r in recs:
            assert r.direction == "YES", f"Should not have NO direction, got {r.direction}"
