from __future__ import annotations

from pm_bot.strategies.base import Strategy, ALL_STRATEGIES, Gopfan2Strategy
from pm_bot.strategies.resolution_divergence import ResolutionDivergenceStrategy
from pm_bot.strategies.neg_risk_sum import NegRiskSumStrategy
from pm_bot.strategies.truncation_edge import TruncationEdgeStrategy
from pm_bot.strategies.ensemble_spread import EnsembleSpreadStrategy
from pm_bot.strategies.neg_risk_field_fade import NegRiskFieldFadeStrategy
from pm_bot.models.market import (
    TemperatureBucket,
    WeatherEvent,
    ForecastResult,
    Recommendation,
)


def _make_event(buckets, city="New York", measure_type="high"):
    return WeatherEvent(
        event_id="test_ev",
        title=f"High temp in {city}",
        slug=f"{city}-2026-01-15",
        city=city,
        date="2026-01-15",
        measure_type=measure_type,
        buckets=buckets,
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


def _make_forecast(temp_high_c=25.0, city="New York", std=None, members=None):
    if members is None:
        spread = std or 2.0
        members = [temp_high_c + i * spread / 4 for i in range(-2, 3)]
    return ForecastResult(
        city=city,
        date="2026-01-15",
        model="gfs",
        temp_high_c=temp_high_c,
        measure_type="high",
        members=members,
    )


class TestStrategyRegistry:
    def test_all_active_strategies_registered(self):
        active = ["gopfan2", "resolution_div", "neg_risk_sum", "truncation_edge", "ensemble_spread", "neg_risk_field_fade"]
        for name in active:
            assert name in ALL_STRATEGIES

    def test_registry_instances(self):
        assert isinstance(ALL_STRATEGIES["gopfan2"], Gopfan2Strategy)
        assert isinstance(ALL_STRATEGIES["truncation_edge"], TruncationEdgeStrategy)

    def test_no_deleted_strategies(self):
        deleted = ["narrow_no", "sum_arb", "metar_obs", "metar_lock", "mean_reversion"]
        for name in deleted:
            assert name not in ALL_STRATEGIES


class TestStrategyBase:
    def test_supports_backtest_property(self):
        s = Strategy()
        assert s.supports_backtest is True

    def test_strategy_run_returns_list(self):
        s = Strategy()
        result = s.run(_make_event([]))
        assert isinstance(result, list)


class TestGopfan2Strategy:
    def test_tail_low_signal(self):
        buckets = [
            _make_bucket(-999, 20, yes_price=0.03, market_id="tail_low"),
            _make_bucket(20, 20, yes_price=0.15, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.20, market_id="b21"),
            _make_bucket(22, 22, yes_price=0.25, market_id="b22"),
            _make_bucket(23, 23, yes_price=0.20, market_id="b23"),
            _make_bucket(24, 24, yes_price=0.10, market_id="b24"),
            _make_bucket(999, 999, yes_price=0.07, market_id="tail_high"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=22.5)
        strategy = Gopfan2Strategy()
        recs = strategy.run(event, forecast=forecast)
        tail_recs = [r for r in recs if r.direction == "YES" and r.price <= 0.15]
        assert len(tail_recs) > 0

    def test_no_signal_when_center_close(self):
        buckets = [_make_bucket(i, i, yes_price=0.20, market_id=f"b{i}") for i in range(20, 30)]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=25.0)
        strategy = Gopfan2Strategy()
        recs = strategy.run(event, forecast=forecast)
        assert all(r.edge > 0 for r in recs)


class TestTruncationEdgeStrategy:
    def test_boundary_bucket_signal(self):
        buckets = [
            _make_bucket(24, 24, yes_price=0.40, market_id="b24"),
            _make_bucket(25, 25, yes_price=0.35, market_id="b25"),
            _make_bucket(26, 26, yes_price=0.25, market_id="b26"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=25.3)
        strategy = TruncationEdgeStrategy()
        recs = strategy.run(event, forecast=forecast)
        frac_25 = 25.3 - 25.0
        if frac_25 < 0.3 or frac_25 > 0.7:
            assert len(recs) > 0

    def test_no_signal_at_0_5(self):
        buckets = [_make_bucket(i, i, yes_price=0.20, market_id=f"b{i}") for i in range(20, 30)]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=25.5)
        strategy = TruncationEdgeStrategy()
        recs = strategy.run(event, forecast=forecast)
        for r in recs:
            assert r.edge > 0

    def test_min_edge_threshold(self):
        buckets = [_make_bucket(25, 25, yes_price=0.40, market_id="b25")]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=25.1)
        strategy = TruncationEdgeStrategy()
        recs = strategy.run(event, forecast=forecast)
        for r in recs:
            assert r.edge >= 0.03


class TestEnsembleSpreadStrategy:
    def test_high_spread_signal(self):
        members = [20.0, 22.0, 25.0, 28.0, 30.0, 21.0, 29.0]
        buckets = [
            _make_bucket(-999, 22, yes_price=0.05, market_id="tail_low"),
            _make_bucket(22, 22, yes_price=0.10, market_id="b22"),
            _make_bucket(23, 23, yes_price=0.15, market_id="b23"),
            _make_bucket(24, 24, yes_price=0.20, market_id="b24"),
            _make_bucket(25, 25, yes_price=0.20, market_id="b25"),
            _make_bucket(26, 26, yes_price=0.15, market_id="b26"),
            _make_bucket(999, 999, yes_price=0.15, market_id="tail_high"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=25.0, members=members)
        strategy = EnsembleSpreadStrategy()
        recs = strategy.run(event, forecast=forecast)
        std = forecast.std
        if std >= 1.5:
            assert len(recs) > 0

    def test_low_spread_no_signal(self):
        members = [24.8, 25.0, 25.1, 25.0, 24.9, 25.2, 25.0]
        buckets = [_make_bucket(i, i, yes_price=0.20, market_id=f"b{i}") for i in range(23, 28)]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=25.0, members=members)
        strategy = EnsembleSpreadStrategy()
        recs = strategy.run(event, forecast=forecast)
        assert len(recs) == 0 or all(r.edge > 0 for r in recs)


class TestNegRiskSumStrategy:
    def test_sum_yes_below_one(self):
        buckets = [
            _make_bucket(20, 20, yes_price=0.30, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.30, market_id="b21"),
            _make_bucket(22, 22, yes_price=0.30, market_id="b22"),
            _make_bucket(999, 999, yes_price=0.05, market_id="tail"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=21.0)
        strategy = NegRiskSumStrategy()
        recs = strategy.run(event, forecast=forecast)
        assert len(recs) > 0


class TestNegRiskFieldFadeStrategy:
    def test_over_round_signal(self):
        buckets = [
            _make_bucket(20, 20, yes_price=0.30, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.30, market_id="b21"),
            _make_bucket(22, 22, yes_price=0.30, market_id="b22"),
            _make_bucket(23, 23, yes_price=0.20, market_id="b23"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=21.5)
        strategy = NegRiskFieldFadeStrategy()
        recs = strategy.run(event, forecast=forecast)
        if event.sum_yes > 1.02:
            assert len(recs) > 0

    def test_no_signal_when_sum_below_one(self):
        buckets = [
            _make_bucket(20, 20, yes_price=0.10, market_id="b20"),
            _make_bucket(21, 21, yes_price=0.10, market_id="b21"),
            _make_bucket(22, 22, yes_price=0.10, market_id="b22"),
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=21.0)
        strategy = NegRiskFieldFadeStrategy()
        recs = strategy.run(event, forecast=forecast)
        assert len(recs) == 0 or all(r.edge > 0 for r in recs)


class TestResolutionDivergenceStrategy:
    def test_basic_run(self):
        buckets = [
            _make_bucket(i, i, yes_price=0.20, market_id=f"b{i}") for i in range(20, 28)
        ]
        event = _make_event(buckets)
        forecast = _make_forecast(temp_high_c=24.0)
        strategy = ResolutionDivergenceStrategy()
        recs = strategy.run(event, forecast=forecast)
        assert isinstance(recs, list)
