from __future__ import annotations

from pm_bot.models.forecast import SourceForecast, ConsensusForecast
from pm_bot.models.config import (
    CITY_COORDS,
    resolve_city_alias,
    STRATEGY_DEFAULTS,
    CACHE_TTL,
)


class TestSourceForecast:
    def test_mean_with_members(self):
        s = SourceForecast(source="nws", temp_high_c=25.0, std_c=2.0, members=[24.0, 25.0, 26.0])
        assert abs(s.mean - 25.0) < 0.01

    def test_mean_without_members(self):
        s = SourceForecast(source="nws", temp_high_c=25.0, std_c=2.0)
        assert s.mean == 25.0

    def test_std_explicit(self):
        s = SourceForecast(source="nws", temp_high_c=25.0, std_c=3.0)
        assert s.std == 3.0

    def test_std_from_members(self):
        s = SourceForecast(source="nws", temp_high_c=25.0, std_c=0.0, members=[22.0, 25.0, 28.0])
        assert s.std > 0

    def test_std_single_member(self):
        s = SourceForecast(source="nws", temp_high_c=25.0, std_c=0.0, members=[25.0])
        assert s.std == 0.0


class TestConsensusForecast:
    def test_default_fields(self):
        c = ConsensusForecast(city="NYC", date="2026-01-01", temp_high_c=25.0, std_c=2.0)
        assert c.consensus_prob == 0.5
        assert c.agreement_score == 1.0
        assert c.sources == {}
        assert c.individual_probs == {}


class TestCityCoords:
    def test_major_cities_present(self):
        for city in ["New York", "London", "Tokyo", "Hong Kong", "Paris", "Lagos"]:
            assert city in CITY_COORDS

    def test_coords_are_tuples(self):
        for city, coords in CITY_COORDS.items():
            assert len(coords) == 2
            assert -90 <= coords[0] <= 90
            assert -180 <= coords[1] <= 180

    def test_paris_is_le_bourget(self):
        assert CITY_COORDS["Paris"][0] == 48.9694


class TestCityAliases:
    def test_nyc_alias(self):
        assert resolve_city_alias("NYC") == "New York"

    def test_la_alias(self):
        assert resolve_city_alias("LA") == "Los Angeles"

    def test_hk_alias(self):
        assert resolve_city_alias("HK") == "Hong Kong"

    def test_unknown_passthrough(self):
        assert resolve_city_alias("Tokyo") == "Tokyo"


class TestStrategyDefaults:
    def test_all_active_strategies_have_defaults(self):
        active = ["gopfan2", "resolution_div", "neg_risk_sum", "truncation_edge", "ensemble_spread", "neg_risk_field_fade"]
        for name in active:
            assert name in STRATEGY_DEFAULTS, f"{name} missing from STRATEGY_DEFAULTS"

    def test_gopfan2_params(self):
        assert "yes_max" in STRATEGY_DEFAULTS["gopfan2"]
        assert "no_min" in STRATEGY_DEFAULTS["gopfan2"]


class TestCacheTTL:
    def test_all_keys_positive(self):
        for key, ttl in CACHE_TTL.items():
            assert ttl > 0, f"CACHE_TTL[{key}] = {ttl} <= 0"
