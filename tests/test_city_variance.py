"""Tests for City Variance Filtering."""

from __future__ import annotations

import pytest
import tempfile
from pathlib import Path

from pm_bot.core.city_variance import (
    CITY_TIER_PRIORS,
    CityVarianceDB,
    CityVarianceEntry,
    DEFAULT_MAX_MAE,
    DEFAULT_MAX_STD,
    filter_recommendations,
    get_tier,
    is_tradeable,
)
from pm_bot.models.market import (
    ForecastResult,
    Recommendation,
    TemperatureBucket,
    WeatherEvent,
)


class TestCityVarianceEntry:
    def test_initial_state(self):
        entry = CityVarianceEntry(city="NYC")
        assert entry.sample_count == 0
        assert entry.mae == 0.0
        assert entry.std == 0.0
        assert entry.tier == "unknown"

    def test_update_single(self):
        entry = CityVarianceEntry(city="NYC")
        entry.update(predicted_c=25.0, observed_c=26.0)
        assert entry.sample_count == 1
        assert entry.mae == 1.0
        assert entry.mean_error == 1.0

    def test_update_multiple(self):
        entry = CityVarianceEntry(city="NYC")
        entry.update(predicted_c=25.0, observed_c=26.0)  # error = +1
        entry.update(predicted_c=25.0, observed_c=24.0)  # error = -1
        entry.update(predicted_c=25.0, observed_c=27.0)  # error = +2
        assert entry.sample_count == 3
        assert entry.mae == pytest.approx(4.0 / 3)  # (1+1+2)/3
        assert entry.mean_error == pytest.approx(2.0 / 3)  # (1-1+2)/3

    def test_tier_classification(self):
        entry = CityVarianceEntry(city="NYC")
        # Low MAE
        for _ in range(15):
            entry.update(predicted_c=25.0, observed_c=25.5)
        assert entry.tier == "low"
        assert entry.mae == pytest.approx(0.5)

    def test_tier_medium(self):
        entry = CityVarianceEntry(city="Chicago")
        # Medium MAE
        for _ in range(15):
            entry.update(predicted_c=25.0, observed_c=27.5)
        assert entry.tier == "medium"
        assert entry.mae == pytest.approx(2.5)

    def test_tier_high(self):
        entry = CityVarianceEntry(city="Chicago")
        # High MAE
        for _ in range(15):
            entry.update(predicted_c=25.0, observed_c=30.0)
        assert entry.tier == "high"
        assert entry.mae == pytest.approx(5.0)

    def test_tier_unknown_with_few_samples(self):
        entry = CityVarianceEntry(city="NYC")
        for _ in range(5):  # Less than MIN_OBSERVATIONS
            entry.update(predicted_c=25.0, observed_c=26.0)
        assert entry.tier == "unknown"

    def test_std_calculation(self):
        entry = CityVarianceEntry(city="NYC")
        # Constant error -> std should be 0
        for _ in range(10):
            entry.update(predicted_c=25.0, observed_c=26.0)
        assert entry.std == pytest.approx(0.0)

        # Varying errors -> std > 0
        entry2 = CityVarianceEntry(city="NYC")
        entry2.update(predicted_c=25.0, observed_c=26.0)
        entry2.update(predicted_c=25.0, observed_c=24.0)
        assert entry2.std > 0


class TestCityVarianceDB:
    @pytest.fixture
    def db(self, tmp_path):
        """Create a temporary DB for testing."""
        return CityVarianceDB(db_path=tmp_path / "test_variance.db")

    def test_record_and_get(self, db):
        db.record("NYC", 25.0, 26.0)
        entry = db.get_entry("NYC")
        assert entry is not None
        assert entry.sample_count == 1
        assert entry.mae == 1.0

    def test_record_multiple_cities(self, db):
        db.record("NYC", 25.0, 26.0)
        db.record("London", 15.0, 16.0)
        db.record("Tokyo", 30.0, 31.0)
        assert db.get_entry("NYC").sample_count == 1
        assert db.get_entry("London").sample_count == 1
        assert db.get_entry("Tokyo").sample_count == 1

    def test_persistence(self, tmp_path):
        db_path = tmp_path / "persist.db"
        db1 = CityVarianceDB(db_path=db_path)
        db1.record("NYC", 25.0, 26.0)
        db1.close()

        db2 = CityVarianceDB(db_path=db_path)
        entry = db2.get_entry("NYC")
        assert entry is not None
        assert entry.sample_count == 1
        assert entry.mae == 1.0

    def test_get_mae_with_data(self, db):
        for _ in range(15):
            db.record("NYC", 25.0, 26.0)
        mae = db.get_mae("NYC")
        assert mae == pytest.approx(1.0)

    def test_get_mae_insufficient_data(self, db):
        db.record("NYC", 25.0, 26.0)
        assert db.get_mae("NYC") is None  # Less than MIN_OBSERVATIONS

    def test_get_tier_with_data(self, db):
        for _ in range(15):
            db.record("NYC", 25.0, 25.5)  # Low MAE
        assert db.get_tier("NYC") == "low"

    def test_get_tier_uses_prior(self, db):
        """When no data, should use prior."""
        assert db.get_tier("Chicago") == "high"
        assert db.get_tier("Miami") == "low"
        assert db.get_tier("NYC") == "medium"

    def test_get_tier_unknown_city(self, db):
        assert db.get_tier("UnknownCity") == "unknown"

    def test_is_tradeable_default(self, db):
        """Default thresholds should pass for most cities."""
        assert db.is_tradeable("NYC") is True
        assert db.is_tradeable("Miami") is True

    def test_is_tradeable_high_variance(self, db):
        """High variance cities should be filtered with strict thresholds."""
        # Chicago has high prior
        assert db.is_tradeable("Chicago", allowed_tiers=["low", "medium"]) is False

    def test_is_tradeable_with_data(self, db):
        """High MAE city should be filtered."""
        for _ in range(15):
            db.record("NYC", 25.0, 30.0)  # MAE = 5.0
        assert db.is_tradeable("NYC", max_mae=3.0) is False
        assert db.is_tradeable("NYC", max_mae=6.0) is True

    def test_get_tradeable_cities(self, db):
        """Should return cities that pass filters."""
        tradeable = db.get_tradeable_cities(allowed_tiers=["low", "medium"])
        assert "Miami" in tradeable
        assert "NYC" in tradeable
        assert "Chicago" not in tradeable  # high prior

    def test_get_all_scores(self, db):
        for _ in range(15):
            db.record("NYC", 25.0, 26.0)
        scores = db.get_all_scores()
        assert len(scores) == 1
        assert scores[0]["city"] == "NYC"
        assert scores[0]["mae"] == pytest.approx(1.0)
        assert scores[0]["tier"] == "low"

    def test_allowed_tiers_filter(self, db):
        """allowed_tiers should filter by tier."""
        for _ in range(15):
            db.record("NYC", 25.0, 25.5)  # low
            db.record("Chicago", 25.0, 30.0)  # high

        assert db.is_tradeable("NYC", allowed_tiers=["low"]) is True
        assert db.is_tradeable("NYC", allowed_tiers=["high"]) is False
        assert db.is_tradeable("Chicago", allowed_tiers=["low"]) is False
        assert db.is_tradeable("Chicago", allowed_tiers=["high"]) is True


class TestFilterRecommendations:
    @pytest.fixture
    def db(self, tmp_path):
        return CityVarianceDB(db_path=tmp_path / "filter_test.db")

    def _make_rec(self, city: str) -> Recommendation:
        event = WeatherEvent(
            event_id="test",
            city=city,
            date="2026-05-13",
            title=f"High Temperature {city}",
            buckets=[],
        )
        bucket = TemperatureBucket(
            temp_low_c=25.0,
            temp_high_c=26.0,
            yes_price=0.50,
            no_price=0.50,
        )
        return Recommendation(
            strategy="test",
            event=event,
            bucket=bucket,
            direction="YES",
            edge=0.10,
            reasoning="test",
            size_usd=2.0,
        )

    def test_filter_passes_normal_cities(self, db):
        recs = [self._make_rec("NYC"), self._make_rec("Miami")]
        filtered = filter_recommendations(recs)
        assert len(filtered) == 2

    def test_filter_blocks_high_variance(self, db):
        """Chicago should be blocked by default (high prior)."""
        recs = [self._make_rec("NYC"), self._make_rec("Chicago")]
        filtered = filter_recommendations(recs, allowed_tiers=["low", "medium"])
        assert len(filtered) == 1
        assert filtered[0].event.city == "NYC"

    def test_filter_with_custom_thresholds(self, db):
        """Custom MAE threshold should filter."""
        for _ in range(15):
            db.record("NYC", 25.0, 30.0)  # MAE = 5.0

        recs = [self._make_rec("NYC")]
        assert len(filter_recommendations(recs, max_mae=3.0)) == 0
        assert len(filter_recommendations(recs, max_mae=6.0)) == 1


class TestConvenienceFunctions:
    def test_is_tradeable_function(self):
        """Module-level function should work."""
        assert is_tradeable("NYC") is True

    def test_get_tier_function(self):
        """Module-level function should work."""
        assert get_tier("Miami") == "low"
        assert get_tier("Chicago") == "high"


class TestCityTierPriors:
    def test_low_tier_cities(self):
        low_cities = ["Miami", "Los Angeles", "San Francisco", "Hong Kong", "Jeddah"]
        for city in low_cities:
            assert CITY_TIER_PRIORS.get(city) == "low", f"{city} should be low"

    def test_high_tier_cities(self):
        high_cities = ["Chicago"]
        for city in high_cities:
            assert CITY_TIER_PRIORS.get(city) == "high", f"{city} should be high"

    def test_medium_tier_cities(self):
        medium_cities = ["NYC", "London", "Tokyo", "Seoul"]
        for city in medium_cities:
            assert CITY_TIER_PRIORS.get(city) == "medium", f"{city} should be medium"
