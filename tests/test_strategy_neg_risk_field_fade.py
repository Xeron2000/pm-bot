from __future__ import annotations

from pm_bot.strategies.neg_risk_field_fade import NegRiskFieldFadeStrategy
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


def _make_forecast(temp_high_c=25.0, members=None):
    if members is None:
        members = [temp_high_c + i * 0.5 for i in range(-2, 3)]
    return ForecastResult(
        city="New York",
        date="2026-01-15",
        model="gfs",
        temp_high_c=temp_high_c,
        measure_type="high",
        members=members,
    )


class TestNegRiskFieldFadeNoOverRound:
    def test_below_threshold(self):
        buckets = [
            _make_bucket(20, 20, yes_price=0.15, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.15, market_id="b21"),
            _make_bucket(22, 22, yes_price=0.15, market_id="b22"),
        ]
        event = _make_event(buckets)
        strategy = NegRiskFieldFadeStrategy()
        recs = strategy.run(event)
        assert len(recs) == 0

    def test_fewer_than_4_buckets(self):
        buckets = [
            _make_bucket(20, 20, yes_price=0.40, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.40, market_id="b21"),
        ]
        event = _make_event(buckets)
        strategy = NegRiskFieldFadeStrategy()
        recs = strategy.run(event)
        assert len(recs) == 0


class TestNegRiskFieldFadeOverRound:
    def test_over_round_with_forecast(self):
        buckets = [
            _make_bucket(20, 20, yes_price=0.30, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.30, market_id="b21"),
            _make_bucket(22, 22, yes_price=0.30, market_id="b22"),
            _make_bucket(23, 23, yes_price=0.20, market_id="b23"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=21.5)
        strategy = NegRiskFieldFadeStrategy()
        recs = strategy.run(event, forecast=forecast)
        assert len(recs) > 0
        assert all(r.direction == "NO" for r in recs)

    def test_over_round_no_forecast(self):
        buckets = [
            _make_bucket(20, 20, yes_price=0.30, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.30, market_id="b21"),
            _make_bucket(22, 22, yes_price=0.30, market_id="b22"),
            _make_bucket(23, 23, yes_price=0.20, market_id="b23"),
        ]
        event = _make_event(buckets)
        strategy = NegRiskFieldFadeStrategy()
        recs = strategy.run(event)
        assert len(recs) > 0

    def test_no_price_below_02(self):
        buckets = [
            _make_bucket(20, 20, yes_price=0.98, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.05, market_id="b21"),
            _make_bucket(22, 22, yes_price=0.05, market_id="b22"),
            _make_bucket(23, 23, yes_price=0.05, market_id="b23"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=21.5)
        strategy = NegRiskFieldFadeStrategy()
        recs = strategy.run(event, forecast=forecast)
        for r in recs:
            assert r.bucket.no_price >= 0.02


class TestNegRiskFieldFadeRankOverpriced:
    def test_with_forecast(self):
        strategy = NegRiskFieldFadeStrategy()
        buckets = [
            _make_bucket(20, 20, yes_price=0.40, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.20, market_id="b21"),
            _make_bucket(22, 22, yes_price=0.10, market_id="b22"),
        ]
        forecast = _make_forecast(temp_high_c=22.0)
        result = strategy._rank_overpriced(buckets, forecast)
        assert len(result) == 3
        assert result[0][0].yes_price >= result[1][0].yes_price or result[0][1] < result[1][1]

    def test_without_forecast(self):
        strategy = NegRiskFieldFadeStrategy()
        buckets = [
            _make_bucket(20, 20, yes_price=0.40, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.20, market_id="b21"),
        ]
        result = strategy._rank_overpriced(buckets, None)
        assert len(result) == 2
        assert result[0][0].yes_price >= result[1][0].yes_price
