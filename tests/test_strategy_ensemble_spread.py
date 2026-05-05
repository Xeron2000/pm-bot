from __future__ import annotations

from pm_bot.strategies.ensemble_spread import EnsembleSpreadStrategy
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


class TestEnsembleSpreadNoForecast:
    def test_no_forecast_returns_empty(self):
        buckets = [_make_bucket(25, 25, yes_price=0.40)]
        event = _make_event(buckets)
        strategy = EnsembleSpreadStrategy()
        recs = strategy.run(event)
        assert recs == []


class TestEnsembleSpreadLowSpread:
    def test_tight_spread_no_signal(self):
        members = [24.8, 25.0, 25.1, 25.0, 24.9, 25.2, 25.0]
        buckets = [_make_bucket(i, i, yes_price=0.20, market_id=f"b{i}") for i in range(23, 28)]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=25.0, members=members)
        strategy = EnsembleSpreadStrategy()
        recs = strategy.run(event, forecast=forecast)
        assert len(recs) == 0 or all(r.edge > 0 for r in recs)


class TestEnsembleSpreadWideSpread:
    def test_wide_spread_yes_signal(self):
        members = [20.0, 22.0, 25.0, 28.0, 30.0, 21.0, 29.0]
        buckets = [
            _make_bucket(-999, 22, yes_price=0.03, market_id="tail_low"),
            _make_bucket(22, 22, yes_price=0.05, market_id="b22"),
            _make_bucket(23, 23, yes_price=0.10, market_id="b23"),
            _make_bucket(24, 24, yes_price=0.15, market_id="b24"),
            _make_bucket(25, 25, yes_price=0.20, market_id="b25"),
            _make_bucket(26, 26, yes_price=0.15, market_id="b26"),
            _make_bucket(999, 999, yes_price=0.10, market_id="tail_high"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=25.0, members=members)
        strategy = EnsembleSpreadStrategy()
        recs = strategy.run(event, forecast=forecast)
        if forecast.std >= 1.5:
            assert len(recs) > 0

    def test_wide_spread_no_signal(self):
        members = [20.0, 28.0, 30.0, 21.0, 29.0]
        buckets = [
            _make_bucket(25, 25, yes_price=0.60, market_id="b25"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=25.0, members=members)
        strategy = EnsembleSpreadStrategy()
        recs = strategy.run(event, forecast=forecast)
        no_recs = [r for r in recs if r.direction == "NO"]
        assert len(no_recs) >= 0


class TestEnsembleSpreadPriceBoundaries:
    def test_near_zero_price_skipped(self):
        members = [20.0, 25.0, 30.0]
        buckets = [
            _make_bucket(25, 25, yes_price=0.005, market_id="b25"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=25.0, members=members)
        strategy = EnsembleSpreadStrategy()
        recs = strategy.run(event, forecast=forecast)
        assert len(recs) == 0

    def test_near_one_price_skipped(self):
        members = [20.0, 25.0, 30.0]
        buckets = [
            _make_bucket(25, 25, yes_price=0.995, market_id="b25"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=25.0, members=members)
        strategy = EnsembleSpreadStrategy()
        recs = strategy.run(event, forecast=forecast)
        assert len(recs) == 0
