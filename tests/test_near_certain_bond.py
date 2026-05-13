"""Tests for Near-Certain Bond strategy, staged entry, and ladder cost constraint."""

from __future__ import annotations

import pytest

from pm_bot.core.staged_entry import apply_staged_entry, get_position_multiplier
from pm_bot.models.market import (
    ForecastResult,
    Recommendation,
    TemperatureBucket,
    WeatherEvent,
)
from pm_bot.strategies.laddering import LadderingStrategy
from pm_bot.strategies.near_certain_bond import NearCertainBondStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bucket(
    temp_low: float,
    temp_high: float,
    temp_unit: str = "C",
    yes_price: float = 0.97,
    market_id: str = "b1",
) -> TemperatureBucket:
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


def _make_event(buckets, city: str = "New York") -> WeatherEvent:
    return WeatherEvent(
        event_id="test_ev",
        title=f"High temp in {city}",
        slug=f"{city}-2026-01-15",
        city=city,
        date="2026-01-15",
        measure_type="high",
        buckets=buckets,
    )


def _make_forecast(temp_high_c: float = 25.0, members: list[float] | None = None) -> ForecastResult:
    if members is None:
        # Tight cluster around temp_high_c → high confidence
        members = [temp_high_c + i * 0.1 for i in range(-2, 3)]
    return ForecastResult(
        city="New York",
        date="2026-01-15",
        model="gfs",
        temp_high_c=temp_high_c,
        measure_type="high",
        members=members,
    )


def _make_rec(size_usd: float = 10.0, strategy: str = "test") -> Recommendation:
    bucket = _make_bucket(25, 26, yes_price=0.50)
    event = _make_event([bucket])
    return Recommendation(
        strategy=strategy,
        event=event,
        bucket=bucket,
        direction="YES",
        edge=0.05,
        reasoning="test",
        size_usd=size_usd,
        kelly_fraction=0.25,
    )


# ---------------------------------------------------------------------------
# R1: Near-Certain Bond Strategy
# ---------------------------------------------------------------------------

class TestNearCertainBondStrategy:
    def test_filters_by_price_range(self):
        """Only buckets with YES price in [0.95, 0.99] should be considered."""
        buckets = [
            _make_bucket(24, 25, yes_price=0.90, market_id="cheap"),  # too low
            _make_bucket(25, 26, yes_price=0.97, market_id="sweet"),  # in range
            _make_bucket(26, 27, yes_price=0.99, market_id="edge"),   # at max
            _make_bucket(27, 28, yes_price=1.00, market_id="over"),   # too high
        ]
        # Make forecast match bucket 25-26 with high probability
        members = [25.3, 25.4, 25.5, 25.6, 25.7]
        forecast = _make_forecast(temp_high_c=25.5, members=members)
        event = _make_event(buckets)
        strategy = NearCertainBondStrategy()
        recs = strategy.run(event, forecast=forecast)

        for r in recs:
            assert 0.95 <= r.bucket.yes_price <= 0.99

    def test_filters_by_model_probability(self):
        """Only buckets with model_prob >= 0.98 should qualify."""
        # All buckets same price, different from forecast center
        buckets = [
            _make_bucket(20, 21, yes_price=0.97, market_id="far"),   # low prob
            _make_bucket(25, 26, yes_price=0.97, market_id="close"),  # high prob
        ]
        # Tight cluster at 25 → high prob for 25-26, low for 20-21
        members = [25.0, 25.1, 25.2, 25.3, 25.4]
        forecast = _make_forecast(temp_high_c=25.2, members=members)
        event = _make_event(buckets)
        strategy = NearCertainBondStrategy(min_model_prob=0.80)  # lower threshold for test
        recs = strategy.run(event, forecast=forecast)

        # Should only get the close bucket
        assert len(recs) == 1
        assert recs[0].bucket.market_id == "close"

    def test_kelly_sizing(self):
        """Position should use Kelly formula with kelly_fraction=0.50."""
        buckets = [_make_bucket(25, 26, yes_price=0.97, market_id="b1")]
        members = [25.0, 25.1, 25.2, 25.3, 25.4]
        forecast = _make_forecast(temp_high_c=25.2, members=members)
        event = _make_event(buckets)
        strategy = NearCertainBondStrategy(
            kelly_fraction=0.50,
            max_position_usd=5.0,
            bankroll=1000.0,
            min_model_prob=0.80,
        )
        recs = strategy.run(event, forecast=forecast)
        assert len(recs) == 1
        r = recs[0]
        # Kelly fraction should be positive (model prob > price)
        assert r.kelly_fraction > 0
        # Size should be bounded by max_position_usd
        assert r.size_usd <= 5.0

    def test_max_per_event(self):
        """Should return at most max_per_event recommendations."""
        buckets = [
            _make_bucket(25, 26, yes_price=0.96, market_id=f"b{i}")
            for i in range(5)
        ]
        members = [25.0, 25.1, 25.2, 25.3, 25.4]
        forecast = _make_forecast(temp_high_c=25.2, members=members)
        event = _make_event(buckets)
        strategy = NearCertainBondStrategy(max_per_event=2, min_model_prob=0.80)
        recs = strategy.run(event, forecast=forecast)
        assert len(recs) <= 2

    def test_no_recs_without_forecast(self):
        """Should return empty if no forecast provided."""
        buckets = [_make_bucket(25, 26, yes_price=0.97)]
        event = _make_event(buckets)
        strategy = NearCertainBondStrategy()
        recs = strategy.run(event)  # no forecast kwarg
        assert recs == []

    def test_direction_is_yes(self):
        """All recommendations should be YES direction."""
        buckets = [_make_bucket(25, 26, yes_price=0.97)]
        members = [25.0, 25.1, 25.2, 25.3, 25.4]
        forecast = _make_forecast(temp_high_c=25.2, members=members)
        event = _make_event(buckets)
        strategy = NearCertainBondStrategy(min_model_prob=0.80)
        recs = strategy.run(event, forecast=forecast)
        for r in recs:
            assert r.direction == "YES"

    def test_default_params_from_config(self):
        """Strategy should pick up defaults from STRATEGY_DEFAULTS."""
        from pm_bot.models.config import STRATEGY_DEFAULTS

        defaults = STRATEGY_DEFAULTS.get("near_certain_bond", {})
        assert defaults["min_yes_price"] == 0.95
        assert defaults["max_yes_price"] == 0.99
        assert defaults["min_model_prob"] == 0.98
        assert defaults["kelly_fraction"] == 0.50
        assert defaults["max_position_usd"] == 5.0


# ---------------------------------------------------------------------------
# R2: Staged Entry
# ---------------------------------------------------------------------------

class TestStagedEntry:
    def test_multiplier_above_48h(self):
        assert get_position_multiplier(50.0) == 0.0

    def test_multiplier_48_to_24h(self):
        assert get_position_multiplier(36.0) == 0.3

    def test_multiplier_24_to_8h(self):
        assert get_position_multiplier(12.0) == 0.6

    def test_multiplier_below_8h(self):
        assert get_position_multiplier(4.0) == 1.0

    def test_multiplier_exact_boundaries(self):
        assert get_position_multiplier(48.0) == 0.3  # 48 is NOT > 48, so next stage
        assert get_position_multiplier(24.0) == 0.6
        assert get_position_multiplier(8.0) == 1.0

    def test_apply_staged_entry_zero_multiplier(self):
        """Should return empty list when multiplier is 0."""
        recs = [_make_rec(size_usd=10.0)]
        result = apply_staged_entry(recs, hours_to_resolution=50.0)
        assert result == []

    def test_apply_staged_entry_scales_size(self):
        """Should scale size_usd by multiplier."""
        recs = [_make_rec(size_usd=10.0)]
        result = apply_staged_entry(recs, hours_to_resolution=12.0)
        assert len(result) == 1
        assert result[0].size_usd == pytest.approx(6.0)  # 10 * 0.6

    def test_apply_staged_entry_preserves_other_fields(self):
        """Should preserve all fields except size_usd."""
        rec = _make_rec(size_usd=10.0, strategy="gopfan2")
        result = apply_staged_entry([rec], hours_to_resolution=4.0)
        assert len(result) == 1
        r = result[0]
        assert r.strategy == "gopfan2"
        assert r.direction == "YES"
        assert r.edge == 0.05
        assert r.size_usd == pytest.approx(10.0)  # 1.0 multiplier

    def test_custom_stages(self):
        """Should accept custom stage configuration."""
        custom = [(100.0, 0.5), (50.0, 0.8), (0.0, 1.0)]
        assert get_position_multiplier(120.0, stages=custom) == 0.0
        assert get_position_multiplier(80.0, stages=custom) == 0.5
        assert get_position_multiplier(30.0, stages=custom) == 0.8
        assert get_position_multiplier(5.0, stages=custom) == 1.0


# ---------------------------------------------------------------------------
# R3: Ladder Total Cost Constraint
# ---------------------------------------------------------------------------

class TestLadderCostConstraint:
    def test_cost_constraint_removes_expensive_buckets(self):
        """When total cost > max_ladder_cost, remove expensive buckets."""
        # Create buckets with high prices that sum > 0.90
        buckets = [
            _make_bucket(24, 25, yes_price=0.40, market_id="b1"),
            _make_bucket(25, 26, yes_price=0.35, market_id="b2"),
            _make_bucket(26, 27, yes_price=0.30, market_id="b3"),
            _make_bucket(27, 28, yes_price=0.05, market_id="b4"),
        ]
        # Forecast center at 25-26
        members = [25.0, 25.1, 25.2, 25.3, 25.4]
        forecast = _make_forecast(temp_high_c=25.2, members=members)
        event = _make_event(buckets)

        strategy = LadderingStrategy(
            max_ladder_cost=0.90,
            min_price=0.01,
            max_price=0.50,
            edge_threshold=0.01,
            spread_degrees=5.0,
            buckets_to_use=4,
        )
        recs = strategy.run(event, forecast=forecast)

        if recs:
            # Total cost of selected buckets should be <= 0.90
            total = sum(r.bucket.yes_price for r in recs)
            assert total <= 0.90 + 0.001  # float tolerance

    def test_cost_constraint_in_reasoning(self):
        """Reasoning should include LADDER COST= annotation."""
        buckets = [
            _make_bucket(24, 25, yes_price=0.20, market_id="b1"),
            _make_bucket(25, 26, yes_price=0.15, market_id="b2"),
            _make_bucket(26, 27, yes_price=0.10, market_id="b3"),
        ]
        members = [25.0, 25.1, 25.2, 25.3, 25.4]
        forecast = _make_forecast(temp_high_c=25.2, members=members)
        event = _make_event(buckets)

        strategy = LadderingStrategy(
            max_ladder_cost=0.90,
            min_price=0.01,
            max_price=0.25,
            edge_threshold=0.01,
            spread_degrees=5.0,
            buckets_to_use=3,
        )
        recs = strategy.run(event, forecast=forecast)

        for r in recs:
            assert "LADDER COST=" in r.reasoning

    def test_no_constraint_when_under_limit(self):
        """When total cost already under limit, all buckets kept."""
        buckets = [
            _make_bucket(24, 25, yes_price=0.10, market_id="b1"),
            _make_bucket(25, 26, yes_price=0.08, market_id="b2"),
            _make_bucket(26, 27, yes_price=0.05, market_id="b3"),
        ]
        members = [25.0, 25.1, 25.2, 25.3, 25.4]
        forecast = _make_forecast(temp_high_c=25.2, members=members)
        event = _make_event(buckets)

        strategy = LadderingStrategy(
            max_ladder_cost=0.90,
            min_price=0.01,
            max_price=0.15,
            edge_threshold=0.01,
            spread_degrees=5.0,
            buckets_to_use=3,
        )
        recs = strategy.run(event, forecast=forecast)
        # All 3 should be kept (total = 0.23 < 0.90)
        assert len(recs) == 3


# ---------------------------------------------------------------------------
# R4: Integration
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_near_certain_bond_in_registry(self):
        """near_certain_bond should be in get_all_strategies()."""
        # Reset cached registry to pick up new strategy
        import pm_bot.strategies.base as base_mod
        base_mod._all_strategies = None

        from pm_bot.strategies.base import get_all_strategies
        strategies = get_all_strategies()
        assert "near_certain_bond" in strategies
        assert isinstance(strategies["near_certain_bond"], NearCertainBondStrategy)

    def test_all_expected_strategies(self):
        """All 6 strategies should be registered."""
        import pm_bot.strategies.base as base_mod
        base_mod._all_strategies = None

        from pm_bot.strategies.base import get_all_strategies
        strategies = get_all_strategies()
        expected = [
            "gopfan2", "laddering", "tail_no_barbell",
            "forecast_arb", "resolution_delay", "near_certain_bond",
        ]
        assert list(strategies.keys()) == expected

    def test_import_from_init(self):
        """NearCertainBondStrategy should be importable from strategies package."""
        from pm_bot.strategies import NearCertainBondStrategy as NCB
        assert NCB is NearCertainBondStrategy
