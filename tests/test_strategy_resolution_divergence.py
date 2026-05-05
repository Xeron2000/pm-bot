from __future__ import annotations

from pm_bot.strategies.resolution_divergence import ResolutionDivergenceStrategy
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


class TestResolutionDivergenceIsDstMonth:
    def test_summer(self):
        s = ResolutionDivergenceStrategy()
        assert s._is_dst_month("2026-06-15") is True

    def test_winter(self):
        s = ResolutionDivergenceStrategy()
        assert s._is_dst_month("2026-01-15") is False

    def test_invalid_date(self):
        s = ResolutionDivergenceStrategy()
        assert s._is_dst_month("invalid") is False


class TestResolutionDivergenceComputeProbs:
    def test_wu_probs(self):
        s = ResolutionDivergenceStrategy()
        buckets = [
            _make_bucket(23, 23, yes_price=0.20),
            _make_bucket(24, 24, yes_price=0.30),
            _make_bucket(25, 25, yes_price=0.40),
        ]
        forecast = _make_forecast(temp_high_c=24.0)
        probs = s._compute_wu_probs(forecast, buckets, is_dst=False)
        assert len(probs) == 3
        assert all(0 <= p <= 1 for p in probs.values())

    def test_nws_probs_dst(self):
        s = ResolutionDivergenceStrategy()
        buckets = [
            _make_bucket(23, 23, yes_price=0.20),
            _make_bucket(24, 24, yes_price=0.30),
        ]
        forecast = _make_forecast(temp_high_c=24.0)
        probs = s._compute_nws_probs(forecast, buckets, is_dst=True, is_frontal=False)
        assert len(probs) == 2

    def test_nws_probs_frontal(self):
        s = ResolutionDivergenceStrategy()
        buckets = [
            _make_bucket(23, 23, yes_price=0.20),
        ]
        forecast = _make_forecast(temp_high_c=24.0)
        probs = s._compute_nws_probs(forecast, buckets, is_dst=False, is_frontal=True)
        assert len(probs) == 1


class TestResolutionDivergenceRun:
    def test_no_forecast_no_recs(self):
        s = ResolutionDivergenceStrategy()
        buckets = [_make_bucket(25, 25, yes_price=0.30)]
        event = _make_event(buckets)
        recs = s.run(event)
        assert recs == []

    def test_with_forecast(self):
        s = ResolutionDivergenceStrategy()
        buckets = [_make_bucket(i, i, yes_price=0.20, market_id=f"b{i}") for i in range(20, 28)]
        event = _make_event(buckets, date="2026-06-15")
        forecast = _make_forecast(temp_high_c=24.0)
        recs = s.run(event, forecast=forecast)
        assert isinstance(recs, list)

    def test_with_frontal_passage(self):
        s = ResolutionDivergenceStrategy()
        buckets = [_make_bucket(i, i, yes_price=0.20, market_id=f"b{i}") for i in range(20, 28)]
        event = _make_event(buckets, date="2026-06-15")
        forecast = _make_forecast(temp_high_c=24.0)
        recs = s.run(event, forecast=forecast, frontal_passage=True)
        assert isinstance(recs, list)

    def test_zero_price_skipped(self):
        s = ResolutionDivergenceStrategy()
        buckets = [
            _make_bucket(25, 25, yes_price=0.0, market_id="zero"),
            _make_bucket(26, 26, yes_price=0.30, market_id="b26"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=26.0)
        recs = s.run(event, forecast=forecast)
        assert all(r.bucket.yes_price > 0 for r in recs)
