from __future__ import annotations

import pytest
from pm_bot.models.market import (
    TemperatureBucket,
    WeatherEvent,
    ForecastResult,
)


@pytest.fixture
def bucket_c() -> TemperatureBucket:
    return TemperatureBucket(
        market_id="test_1",
        question="23°C",
        temp_low=23.0,
        temp_high=23.0,
        temp_unit="C",
        yes_price=0.20,
        no_price=0.80,
        volume=500.0,
    )


@pytest.fixture
def bucket_f() -> TemperatureBucket:
    return TemperatureBucket(
        market_id="test_f",
        question="between 90-91°F",
        temp_low=90.0,
        temp_high=91.0,
        temp_unit="F",
        yes_price=0.15,
        no_price=0.85,
        volume=300.0,
    )


@pytest.fixture
def tail_low_bucket() -> TemperatureBucket:
    return TemperatureBucket(
        market_id="tail_low",
        question="16°C or below",
        temp_low=-999.0,
        temp_high=16.0,
        temp_unit="C",
        yes_price=0.03,
        no_price=0.97,
        volume=200.0,
    )


@pytest.fixture
def tail_high_bucket() -> TemperatureBucket:
    return TemperatureBucket(
        market_id="tail_high",
        question="27°C or higher",
        temp_low=27.0,
        temp_high=999.0,
        temp_unit="C",
        yes_price=0.05,
        no_price=0.95,
        volume=200.0,
    )


@pytest.fixture
def weather_event(bucket_c) -> WeatherEvent:
    return WeatherEvent(
        event_id="ev_1",
        title="High temp in New York on 2026-01-15",
        slug="new-york-2026-01-15",
        city="New York",
        date="2026-01-15",
        measure_type="high",
        buckets=[bucket_c],
    )


@pytest.fixture
def forecast() -> ForecastResult:
    return ForecastResult(
        city="New York",
        date="2026-01-15",
        model="gfs_seamless",
        temp_high_c=23.4,
        measure_type="high",
        members=[22.1, 23.0, 23.4, 23.8, 24.2, 22.5, 23.1],
    )


@pytest.fixture
def forecast_low_std() -> ForecastResult:
    return ForecastResult(
        city="New York",
        date="2026-01-15",
        model="gfs_seamless",
        temp_high_c=23.0,
        measure_type="high",
        members=[22.8, 23.0, 23.1, 22.9, 23.0, 23.2, 23.1],
    )


@pytest.fixture
def forecast_f() -> ForecastResult:
    return ForecastResult(
        city="Miami",
        date="2026-06-15",
        model="gfs_seamless",
        temp_high_c=33.0,
        measure_type="high",
        members=[32.0, 32.5, 33.0, 33.5, 34.0, 32.8, 33.2],
    )


@pytest.fixture
def multi_bucket_event() -> WeatherEvent:
    buckets = []
    for i in range(-2, 4):
        temp = 23 + i
        buckets.append(TemperatureBucket(
            market_id=f"mb_{i}",
            question=f"{temp}°C",
            temp_low=float(temp),
            temp_high=float(temp),
            temp_unit="C",
            yes_price=0.15 if abs(i) <= 1 else 0.05,
            no_price=0.85 if abs(i) <= 1 else 0.95,
            volume=500.0,
        ))
    buckets.append(TemperatureBucket(
        market_id="mb_tail_low",
        question="20°C or below",
        temp_low=-999.0,
        temp_high=20.0,
        temp_unit="C",
        yes_price=0.02,
        no_price=0.98,
        volume=100.0,
    ))
    buckets.append(TemperatureBucket(
        market_id="mb_tail_high",
        question="27°C or higher",
        temp_low=27.0,
        temp_high=999.0,
        temp_unit="C",
        yes_price=0.04,
        no_price=0.96,
        volume=100.0,
    ))
    return WeatherEvent(
        event_id="ev_multi",
        title="High temp in New York on 2026-01-15",
        slug="new-york-2026-01-15",
        city="New York",
        date="2026-01-15",
        measure_type="high",
        buckets=buckets,
    )
