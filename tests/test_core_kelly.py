from __future__ import annotations

from pm_bot.core.kelly import kelly_fraction, kelly_size, compute_kelly_for_recommendation
from pm_bot.models.market import TemperatureBucket, WeatherEvent, Recommendation


class TestKellyFraction:
    def test_yes_positive_edge(self):
        frac = kelly_fraction(p_true=0.8, yes_price=0.5, direction="YES", kelly_multiplier=0.25)
        assert frac > 0

    def test_yes_zero_edge(self):
        frac = kelly_fraction(p_true=0.5, yes_price=0.5, direction="YES", kelly_multiplier=0.25)
        assert frac == 0.0

    def test_yes_negative_edge(self):
        frac = kelly_fraction(p_true=0.3, yes_price=0.5, direction="YES", kelly_multiplier=0.25)
        assert frac == 0.0

    def test_no_positive_edge(self):
        frac = kelly_fraction(p_true=0.2, yes_price=0.5, direction="NO", kelly_multiplier=0.25)
        assert frac > 0

    def test_no_zero_edge(self):
        frac = kelly_fraction(p_true=0.5, yes_price=0.5, direction="NO", kelly_multiplier=0.25)
        assert frac == 0.0

    def test_no_negative_edge(self):
        frac = kelly_fraction(p_true=0.9, yes_price=0.5, direction="NO", kelly_multiplier=0.25)
        assert frac == 0.0

    def test_quarter_kelly_reduction(self):
        full = kelly_fraction(p_true=0.8, yes_price=0.5, direction="YES", kelly_multiplier=1.0)
        quarter = kelly_fraction(p_true=0.8, yes_price=0.5, direction="YES", kelly_multiplier=0.25)
        assert abs(quarter - full * 0.25) < 0.001

    def test_zero_payout(self):
        frac = kelly_fraction(p_true=0.99, yes_price=1.0, direction="YES", kelly_multiplier=0.25)
        assert frac == 0.0


class TestKellySize:
    def test_positive_edge(self):
        size = kelly_size(edge=0.3, yes_price=0.5, bankroll=100.0, kelly_fraction_val=0.25, max_single=50.0)
        assert size > 0

    def test_zero_edge(self):
        size = kelly_size(edge=0.0, yes_price=0.5, bankroll=100.0, kelly_fraction_val=0.25, max_single=50.0)
        assert size == 0.0

    def test_max_single_cap(self):
        size = kelly_size(edge=0.5, yes_price=0.1, bankroll=10000.0, kelly_fraction_val=0.25, max_single=50.0)
        assert size <= 50.0 / 0.1 + 0.01

    def test_notional_equals_wager_over_price(self):
        size = kelly_size(edge=0.2, yes_price=0.5, bankroll=100.0, kelly_fraction_val=0.25, max_single=50.0)
        full_kelly = 0.2 / 0.5
        wager = 100.0 * full_kelly * 0.25
        expected_notional = wager / 0.5
        assert abs(size - expected_notional) < 0.01

    def test_zero_price(self):
        size = kelly_size(edge=0.3, yes_price=0.0, bankroll=100.0, kelly_fraction_val=0.25, max_single=50.0)
        assert size == 0.0


class TestComputeKellyForRecommendation:
    def _make_rec(self, direction="YES", edge=0.1, yes_price=0.3) -> Recommendation:
        bucket = TemperatureBucket(
            market_id="k1", question="23°C",
            temp_low=23.0, temp_high=23.0, temp_unit="C",
            yes_price=yes_price, no_price=1.0 - yes_price, volume=100.0,
        )
        event = WeatherEvent(
            event_id="e1", title="t", slug="s",
            city="NYC", date="2026-01-01", buckets=[bucket],
        )
        return Recommendation(
            strategy="test", event=event, bucket=bucket,
            direction=direction, edge=edge, reasoning="test",
        )

    def test_basic_yes(self):
        rec = self._make_rec(direction="YES", edge=0.1, yes_price=0.3)
        result = compute_kelly_for_recommendation(rec, bankroll=100.0)
        assert result is not None
        assert result.size_usd > 0

    def test_too_small_rejected(self):
        rec = self._make_rec(direction="YES", edge=0.001, yes_price=0.5)
        result = compute_kelly_for_recommendation(rec, bankroll=1.0)
        assert result is None

    def test_daily_limit(self):
        rec = self._make_rec(direction="YES", edge=0.3, yes_price=0.3)
        result = compute_kelly_for_recommendation(rec, bankroll=100.0, daily_spent=199.0, max_daily=200.0)
        if result is not None:
            assert result.size_usd <= 1.0

    def test_city_limit(self):
        rec = self._make_rec(direction="YES", edge=0.3, yes_price=0.3)
        result = compute_kelly_for_recommendation(rec, bankroll=100.0, city_spent=99.0, max_per_city=100.0)
        if result is not None:
            assert result.size_usd <= 1.0

    def test_total_exposure_limit(self):
        rec = self._make_rec(direction="YES", edge=0.3, yes_price=0.3)
        result = compute_kelly_for_recommendation(
            rec, bankroll=100.0,
            total_exposure=28.0, max_total_pct=0.30,
        )
        if result is not None:
            assert result.size_usd <= 2.0

    def test_zero_price_returns_none(self):
        bucket = TemperatureBucket(
            market_id="k1", question="23°C",
            temp_low=23.0, temp_high=23.0, temp_unit="C",
            yes_price=0.0, no_price=1.0, volume=100.0,
        )
        event = WeatherEvent(
            event_id="e1", title="t", slug="s",
            city="NYC", date="2026-01-01", buckets=[bucket],
        )
        rec = Recommendation(
            strategy="test", event=event, bucket=bucket,
            direction="YES", edge=0.1, reasoning="test",
        )
        result = compute_kelly_for_recommendation(rec, bankroll=100.0)
        assert result is None
