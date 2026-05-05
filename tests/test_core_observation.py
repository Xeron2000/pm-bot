from __future__ import annotations

from pm_bot.core.observation import (
    ObservedTemp,
    should_filter_bucket,
    filter_recommendations,
    resolve_icao_from_description,
    get_icao,
    CITY_ICAO,
    CITY_TZ,
    CUTOFF_HOUR,
)
from pm_bot.models.market import (
    TemperatureBucket,
    WeatherEvent,
    Recommendation,
)
from datetime import datetime, timezone


class TestObservedTemp:
    def test_basic_creation(self):
        obs = ObservedTemp(
            city="New York", observed_c=25.0,
            obs_time_utc=datetime.now(timezone.utc),
            local_time=datetime.now(timezone.utc),
            is_past_cutoff=True,
        )
        assert obs.observed_c == 25.0
        assert obs.is_past_cutoff is True
        assert obs.anomaly_detected is False


class TestShouldFilterBucket:
    def test_not_past_cutoff_no_filter(self):
        obs = ObservedTemp(
            city="NYC", observed_c=25.0,
            obs_time_utc=datetime.now(timezone.utc),
            local_time=datetime.now(timezone.utc),
            is_past_cutoff=False,
        )
        assert should_filter_bucket(23.0, obs) is False

    def test_high_temp_filter_below_floor(self):
        obs = ObservedTemp(
            city="NYC", observed_c=25.4,
            obs_time_utc=datetime.now(timezone.utc),
            local_time=datetime.now(timezone.utc),
            is_past_cutoff=True,
        )
        assert should_filter_bucket(20.0, obs) is True
        assert should_filter_bucket(24.0, obs) is True

    def test_high_temp_no_filter_at_floor(self):
        obs = ObservedTemp(
            city="NYC", observed_c=25.4,
            obs_time_utc=datetime.now(timezone.utc),
            local_time=datetime.now(timezone.utc),
            is_past_cutoff=True,
        )
        assert should_filter_bucket(25.0, obs) is False

    def test_high_temp_no_filter_above_floor(self):
        obs = ObservedTemp(
            city="NYC", observed_c=25.4,
            obs_time_utc=datetime.now(timezone.utc),
            local_time=datetime.now(timezone.utc),
            is_past_cutoff=True,
        )
        assert should_filter_bucket(26.0, obs) is False

    def test_filter_below_observed_floor(self):
        obs = ObservedTemp(
            city="NYC", observed_c=25.4,
            obs_time_utc=datetime.now(timezone.utc),
            local_time=datetime.now(timezone.utc),
            is_past_cutoff=True,
        )
        assert should_filter_bucket(23.0, obs) is True
        assert should_filter_bucket(24.0, obs) is True

    def test_no_filter_at_or_above_floor(self):
        obs = ObservedTemp(
            city="NYC", observed_c=25.4,
            obs_time_utc=datetime.now(timezone.utc),
            local_time=datetime.now(timezone.utc),
            is_past_cutoff=True,
        )
        assert should_filter_bucket(25.0, obs) is False
        assert should_filter_bucket(26.0, obs) is False

    def test_tail_low_inf_not_filtered(self):
        obs = ObservedTemp(
            city="NYC", observed_c=25.4,
            obs_time_utc=datetime.now(timezone.utc),
            local_time=datetime.now(timezone.utc),
            is_past_cutoff=True,
        )
        assert should_filter_bucket(float("-inf"), obs) is False


class TestFilterRecommendations:
    def _make_obs(self, observed_c=25.4, is_past_cutoff=True):
        return ObservedTemp(
            city="NYC", observed_c=observed_c,
            obs_time_utc=datetime.now(timezone.utc),
            local_time=datetime.now(timezone.utc),
            is_past_cutoff=is_past_cutoff,
            
        )

    def _make_rec(self, direction, temp_low=23.0, temp_high=23.0, yes_price=0.2):
        bucket = TemperatureBucket(
            market_id="f1", question=f"{temp_low}°C",
            temp_low=float(temp_low), temp_high=float(temp_high), temp_unit="C",
            yes_price=yes_price, no_price=1.0 - yes_price, volume=100.0,
        )
        event = WeatherEvent(
            event_id="e1", title="t", slug="s",
            city="NYC", date="2026-01-01", buckets=[bucket],
        )
        return Recommendation(
            strategy="test", event=event, bucket=bucket,
            direction=direction, edge=0.05, reasoning="test",
        )

    def test_no_obs_no_filter(self):
        recs = [self._make_rec("YES", 23)]
        result = filter_recommendations(recs, None)
        assert len(result) == 1

    def test_not_past_cutoff_no_filter(self):
        obs = self._make_obs(is_past_cutoff=False)
        recs = [self._make_rec("YES", 23)]
        result = filter_recommendations(recs, obs)
        assert len(result) == 1

    def test_filter_impossible_yes(self):
        obs = self._make_obs(observed_c=25.4)
        rec = self._make_rec("YES", temp_low=20)
        result = filter_recommendations([rec], obs)
        assert len(result) == 0

    def test_keep_possible_yes(self):
        obs = self._make_obs(observed_c=25.4)
        rec = self._make_rec("YES", temp_low=25)
        result = filter_recommendations([rec], obs)
        assert len(result) == 1

    def test_filter_confirmed_no(self):
        obs = self._make_obs(observed_c=25.4)
        rec = self._make_rec("NO", temp_low=25)
        result = filter_recommendations([rec], obs)
        assert len(result) == 0

    def test_keep_unconfirmed_no(self):
        obs = self._make_obs(observed_c=25.4)
        rec = self._make_rec("NO", temp_low=26)
        result = filter_recommendations([rec], obs)
        assert len(result) == 1


class TestResolveIcao:
    def test_from_wunderground_url(self):
        desc = "https://www.wunderground.com/history/daily/us/ny/KLGA"
        icao = resolve_icao_from_description(desc)
        assert icao == "KLGA"

    def test_from_paris_le_bourget(self):
        desc = "https://www.wunderground.com/history/daily/fr/paris/LFPB"
        icao = resolve_icao_from_description(desc)
        assert icao == "LFPB"

    def test_no_wunderground_url(self):
        icao = resolve_icao_from_description("Some random text")
        assert icao is None

    def test_non_capitalized_url(self):
        desc = "https://www.Wunderground.com/history/daily/fr/paris/lfpb"
        icao = resolve_icao_from_description(desc)
        assert icao == "LFPB"


class TestGetIcao:
    def test_static_lookup(self):
        icao = get_icao("New York")
        assert icao == "KLGA"

    def test_dynamic_override(self):
        desc = "https://www.wunderground.com/history/daily/fr/paris/LFPB"
        icao = get_icao("Paris", description=desc)
        assert icao == "LFPB"

    def test_paris_static_is_le_bourget(self):
        assert CITY_ICAO["Paris"] == "LFPB"

    def test_unknown_city(self):
        icao = get_icao("Unknown City")
        assert icao is None


class TestCutoffHour:
    def test_cutoff_5pm(self):
        assert CUTOFF_HOUR == 17


class TestCityTimezones:
    def test_all_icao_cities_have_tz(self):
        for city in CITY_ICAO:
            assert city in CITY_TZ, f"Missing timezone for {city}"

    def test_nyc_eastern(self):
        assert CITY_TZ["New York"] == "America/New_York"

    def test_tokyo_jst(self):
        assert CITY_TZ["Tokyo"] == "Asia/Tokyo"
