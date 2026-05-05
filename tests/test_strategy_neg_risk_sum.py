from __future__ import annotations

from pm_bot.strategies.neg_risk_sum import NegRiskSumStrategy
from pm_bot.models.market import (
    TemperatureBucket,
    WeatherEvent,
    ForecastResult,
)


def _make_bucket(temp_low, temp_high, temp_unit="C", yes_price=0.2, market_id="b1"):
    return TemperatureBucket(
        market_id=market_id,
        question=f"{temp_low}°C",
        temp_low=float(temp_low),
        temp_high=float(temp_high),
        temp_unit=temp_unit,
        yes_price=yes_price,
        no_price=1.0 - yes_price,
        volume=500.0,
    )


def _make_event(buckets, city="New York"):
    return WeatherEvent(
        event_id="test_ev",
        title=f"High temp in {city}",
        slug=f"{city}-2026-01-15",
        city=city,
        date="2026-01-15",
        buckets=buckets,
    )


def _make_forecast(temp_high_c=25.0, city="New York", members=None):
    if members is None:
        members = [temp_high_c + i * 0.5 for i in range(-2, 3)]
    return ForecastResult(
        city=city,
        date="2026-01-15",
        model="gfs",
        temp_high_c=temp_high_c,
        measure_type="high",
        members=members,
    )


class TestNegRiskSumOverRound:
    def test_over_round_no_forecast(self):
        buckets = [
            _make_bucket(20, 20, yes_price=0.35, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.35, market_id="b21"),
            _make_bucket(22, 22, yes_price=0.35, market_id="b22"),
        ]
        event = _make_event(buckets)
        strategy = NegRiskSumStrategy()
        recs = strategy.run(event)
        assert len(recs) > 0
        assert all(r.direction == "NO" for r in recs)

    def test_over_round_with_forecast(self):
        buckets = [
            _make_bucket(20, 20, yes_price=0.35, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.35, market_id="b21"),
            _make_bucket(22, 22, yes_price=0.35, market_id="b22"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=21.0)
        strategy = NegRiskSumStrategy()
        recs = strategy.run(event, forecast=forecast)
        assert len(recs) > 0

    def test_under_round(self):
        buckets = [
            _make_bucket(20, 20, yes_price=0.25, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.25, market_id="b21"),
            _make_bucket(22, 22, yes_price=0.25, market_id="b22"),
            _make_bucket(999, 999, yes_price=0.05, market_id="tail"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=21.0)
        strategy = NegRiskSumStrategy()
        recs = strategy.run(event, forecast=forecast)
        assert len(recs) > 0

    def test_no_active_buckets(self):
        buckets = [
            _make_bucket(20, 20, yes_price=0.0, market_id="b20"),
        ]
        event = _make_event(buckets)
        strategy = NegRiskSumStrategy()
        recs = strategy.run(event)
        assert len(recs) == 0

    def test_near_one_no_signal(self):
        buckets = [
            _make_bucket(20, 20, yes_price=0.33, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.33, market_id="b21"),
            _make_bucket(22, 22, yes_price=0.33, market_id="b22"),
        ]
        event = _make_event(buckets)
        strategy = NegRiskSumStrategy()
        recs = strategy.run(event)
        assert len(recs) == 0 or all(r.edge > 0 for r in recs)


class TestNegRiskSumFindOverpriced:
    def test_returns_sorted(self):
        buckets = [
            _make_bucket(20, 20, yes_price=0.60, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.30, market_id="b21"),
            _make_bucket(22, 22, yes_price=0.05, market_id="b22"),
        ]
        forecast = _make_forecast(temp_high_c=22.0)
        strategy = NegRiskSumStrategy()
        result = strategy._find_overpriced(buckets, forecast)
        assert len(result) > 0
        for b, model_prob in result:
            assert b.yes_price > model_prob + 0.01
