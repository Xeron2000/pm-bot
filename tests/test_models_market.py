from __future__ import annotations


from pm_bot.models.market import (
    TemperatureBucket,
    WeatherEvent,
    ForecastResult,
    Recommendation,
)


class TestTemperatureBucket:
    def test_is_low_tail(self, tail_low_bucket):
        assert tail_low_bucket.is_low_tail is True
        assert tail_low_bucket.is_high_tail is False

    def test_is_high_tail(self, tail_high_bucket):
        assert tail_high_bucket.is_high_tail is True
        assert tail_high_bucket.is_low_tail is False

    def test_normal_bucket_not_tail(self, bucket_c):
        assert bucket_c.is_low_tail is False
        assert bucket_c.is_high_tail is False

    def test_temp_low_c_celsius(self, bucket_c):
        assert bucket_c.temp_low_c == 23.0

    def test_temp_high_c_celsius(self, bucket_c):
        assert bucket_c.temp_high_c == 23.0

    def test_temp_low_c_fahrenheit(self, bucket_f):
        expected = (90.0 - 32) / 1.8
        assert abs(bucket_f.temp_low_c - expected) < 0.01

    def test_temp_high_c_fahrenheit(self, bucket_f):
        expected = (91.0 - 32) / 1.8
        assert abs(bucket_f.temp_high_c - expected) < 0.01

    def test_temp_low_c_tail_low(self, tail_low_bucket):
        assert tail_low_bucket.temp_low_c == float("-inf")

    def test_temp_high_c_tail_high(self, tail_high_bucket):
        assert tail_high_bucket.temp_high_c == float("inf")

    def test_temp_center_c_normal(self, bucket_c):
        assert bucket_c.temp_center_c == 23.0

    def test_temp_center_c_tail_low(self, tail_low_bucket):
        assert tail_low_bucket.temp_center_c == 16.0

    def test_temp_center_c_tail_high(self, tail_high_bucket):
        assert tail_high_bucket.temp_center_c == 27.0

    def test_temp_center_c_both_tails(self):
        b = TemperatureBucket(
            market_id="x", question="x",
            temp_low=-999.0, temp_high=999.0, temp_unit="C",
            yes_price=0.5, no_price=0.5, volume=0.0,
        )
        assert b.temp_center_c == 0.0

    def test_temp_center_c_range(self):
        b = TemperatureBucket(
            market_id="x", question="x",
            temp_low=20.0, temp_high=25.0, temp_unit="C",
            yes_price=0.5, no_price=0.5, volume=0.0,
        )
        assert b.temp_center_c == 22.5


class TestWeatherEvent:
    def test_sum_yes(self, weather_event):
        assert abs(weather_event.sum_yes - 0.20) < 0.001

    def test_sum_gap(self, weather_event):
        assert abs(weather_event.sum_gap - 0.80) < 0.001

    def test_multi_bucket_sum(self, multi_bucket_event):
        assert multi_bucket_event.sum_yes > 0

    def test_measure_type_default(self, bucket_c):
        ev = WeatherEvent(
            event_id="e", title="t", slug="s",
            city="NYC", date="2026-01-01",
            buckets=[bucket_c],
        )
        assert ev.measure_type == "high"


class TestForecastResult:
    def test_mean_with_members(self, forecast):
        expected = sum(forecast.members) / len(forecast.members)
        assert abs(forecast.mean - expected) < 0.01

    def test_mean_without_members(self):
        f = ForecastResult(city="NYC", date="2026-01-01", model="gfs", temp_high_c=25.0)
        assert f.mean == 25.0

    def test_std_with_members(self, forecast):
        assert forecast.std > 0

    def test_std_without_members(self):
        f = ForecastResult(city="NYC", date="2026-01-01", model="gfs", temp_high_c=25.0)
        assert f.std == 0.0

    def test_std_single_member(self):
        f = ForecastResult(city="NYC", date="2026-01-01", model="gfs", temp_high_c=25.0, members=[25.0])
        assert f.std == 0.0


class TestRecommendation:
    def test_city_property(self, weather_event, bucket_c):
        rec = Recommendation(
            strategy="test", event=weather_event, bucket=bucket_c,
            direction="YES", edge=0.05, reasoning="test",
        )
        assert rec.city == "New York"

    def test_temp_label_normal(self, weather_event, bucket_c):
        rec = Recommendation(
            strategy="test", event=weather_event, bucket=bucket_c,
            direction="YES", edge=0.05, reasoning="test",
        )
        assert "23°C" in rec.temp_label

    def test_temp_label_tail_low(self, weather_event, tail_low_bucket):
        rec = Recommendation(
            strategy="test", event=weather_event, bucket=tail_low_bucket,
            direction="YES", edge=0.05, reasoning="test",
        )
        assert "≤" in rec.temp_label

    def test_temp_label_tail_high(self, weather_event, tail_high_bucket):
        rec = Recommendation(
            strategy="test", event=weather_event, bucket=tail_high_bucket,
            direction="YES", edge=0.05, reasoning="test",
        )
        assert "≥" in rec.temp_label

    def test_price_yes(self, weather_event, bucket_c):
        rec = Recommendation(
            strategy="test", event=weather_event, bucket=bucket_c,
            direction="YES", edge=0.05, reasoning="test",
        )
        assert rec.price == 0.20

    def test_price_no(self, weather_event, bucket_c):
        rec = Recommendation(
            strategy="test", event=weather_event, bucket=bucket_c,
            direction="NO", edge=0.05, reasoning="test",
        )
        assert rec.price == 0.80
