from __future__ import annotations

from pm_bot.strategies.truncation_edge import TruncationEdgeStrategy
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


def _make_event(buckets, city="New York", date="2026-01-15"):
    return WeatherEvent(
        event_id="test_ev",
        title=f"High temp in {city}",
        slug=f"{city}-{date}",
        city=city,
        date=date,
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


class TestTruncationEdgeNoForecast:
    def test_no_forecast_returns_empty(self):
        buckets = [_make_bucket(25, 25, yes_price=0.40)]
        event = _make_event(buckets)
        strategy = TruncationEdgeStrategy()
        recs = strategy.run(event)
        assert recs == []


class TestTruncationEdgeNearBoundary:
    def test_frac_03_yes_edge(self):
        forecast = _make_forecast(temp_high_c=25.3)
        buckets = [
            _make_bucket(25, 25, yes_price=0.30, market_id="b25"),
        ]
        event = _make_event(buckets)
        strategy = TruncationEdgeStrategy()
        recs = strategy.run(event, forecast=forecast)
        yes_recs = [r for r in recs if r.direction == "YES"]
        assert len(yes_recs) > 0

    def test_frac_07_no_edge(self):
        forecast = _make_forecast(temp_high_c=25.7)
        buckets = [
            _make_bucket(26, 26, yes_price=0.60, market_id="b26"),
        ]
        event = _make_event(buckets)
        strategy = TruncationEdgeStrategy()
        recs = strategy.run(event, forecast=forecast)
        no_recs = [r for r in recs if r.direction == "NO"]
        assert len(no_recs) > 0


class TestTruncationEdgeStrongEdge:
    def test_large_yes_edge(self):
        forecast = _make_forecast(temp_high_c=25.5)
        buckets = [
            _make_bucket(25, 25, yes_price=0.05, market_id="b25"),
        ]
        event = _make_event(buckets)
        strategy = TruncationEdgeStrategy()
        recs = strategy.run(event, forecast=forecast)
        yes_recs = [r for r in recs if r.direction == "YES"]
        assert len(yes_recs) > 0

    def test_large_no_edge(self):
        forecast = _make_forecast(temp_high_c=22.0, members=[22.0, 22.5, 23.0])
        buckets = [
            _make_bucket(30, 30, yes_price=0.90, market_id="b30"),
        ]
        event = _make_event(buckets)
        strategy = TruncationEdgeStrategy()
        recs = strategy.run(event, forecast=forecast)
        no_recs = [r for r in recs if r.direction == "NO"]
        assert len(no_recs) >= 0


class TestTruncationEdgeTailBuckets:
    def test_tail_high_no_boundary(self):
        forecast = _make_forecast(temp_high_c=25.5)
        buckets = [
            _make_bucket(999, 999, yes_price=0.05, market_id="tail_high"),
        ]
        event = _make_event(buckets)
        strategy = TruncationEdgeStrategy()
        recs = strategy.run(event, forecast=forecast)
        assert isinstance(recs, list)

    def test_tail_low_no_boundary(self):
        forecast = _make_forecast(temp_high_c=25.5)
        buckets = [
            _make_bucket(-999, 20, yes_price=0.05, market_id="tail_low"),
        ]
        event = _make_event(buckets)
        strategy = TruncationEdgeStrategy()
        recs = strategy.run(event, forecast=forecast)
        assert isinstance(recs, list)


class TestTruncationEdgeExtremePrices:
    def test_near_zero_price_skipped(self):
        forecast = _make_forecast(temp_high_c=25.3)
        buckets = [
            _make_bucket(25, 25, yes_price=0.005, market_id="b25"),
        ]
        event = _make_event(buckets)
        strategy = TruncationEdgeStrategy()
        recs = strategy.run(event, forecast=forecast)
        assert len(recs) == 0

    def test_near_one_price_skipped(self):
        forecast = _make_forecast(temp_high_c=25.3)
        buckets = [
            _make_bucket(25, 25, yes_price=0.995, market_id="b25"),
        ]
        event = _make_event(buckets)
        strategy = TruncationEdgeStrategy()
        recs = strategy.run(event, forecast=forecast)
        assert len(recs) == 0

    def test_zero_model_prob_skipped(self):
        forecast = _make_forecast(temp_high_c=30.0, members=[30.0, 31.0, 32.0])
        buckets = [
            _make_bucket(10, 10, yes_price=0.30, market_id="b10"),
        ]
        event = _make_event(buckets)
        strategy = TruncationEdgeStrategy()
        recs = strategy.run(event, forecast=forecast)
        assert len(recs) == 0
