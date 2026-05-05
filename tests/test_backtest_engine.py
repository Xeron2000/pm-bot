from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pm_bot.backtest.engine import BacktestEngine, BacktestResult, SimulatedTrade
from pm_bot.backtest.real_data import (
    ResolvedEvent,
    ResolvedMarket,
)
from pm_bot.models.market import ForecastResult, TemperatureBucket, Recommendation
from pm_bot.strategies.base import Strategy


class TestSimulatedTrade:
    def test_defaults(self):
        t = SimulatedTrade(
            date="2026-01-15", strategy="test", bucket_key="25-26",
            direction="YES", price=0.5, size_usd=10.0, cost=0.5,
        )
        assert t.pnl == 0.0
        assert t.resolved is False
        assert t.entry_price == 0.0
        assert t.stop_loss_pct == 0.0

    def test_with_values(self):
        t = SimulatedTrade(
            date="2026-01-15", strategy="test", bucket_key="25-26",
            direction="YES", price=0.5, size_usd=10.0, cost=0.5,
            pnl=5.0, resolved=True, entry_price=0.5, stop_loss_pct=0.3,
        )
        assert t.pnl == 5.0
        assert t.resolved is True
        assert t.entry_price == 0.5
        assert t.stop_loss_pct == 0.3


class TestBacktestResult:
    def test_defaults(self):
        r = BacktestResult(strategy_name="test", bankroll=100.0, final_value=110.0, total_pnl=10.0)
        assert r.trades == []
        assert r.sharpe_ratio == 0.0
        assert r.max_drawdown == 0.0
        assert r.win_rate == 0.0


class TestDummyStrategy:
    class DummyStrategy(Strategy):
        name = "dummy"

        def run(self, event, **kwargs):
            return []

    class ProducingStrategy(Strategy):
        name = "producing"

        def run(self, event, **kwargs):
            bucket = TemperatureBucket(
                market_id="m1", question="25°C",
                temp_low=25.0, temp_high=25.0, temp_unit="C",
                yes_price=0.30, no_price=0.70, volume=500.0,
            )
            rec = Recommendation(
                strategy="producing", event=event, bucket=bucket,
                direction="YES", edge=0.15, reasoning="test",
                size_usd=10.0, kelly_fraction=0.25,
            )
            return [rec]


class TestBacktestEngineBuildSyntheticEvent:
    def test_basic(self):
        engine = BacktestEngine(strategies=[])
        forecast = ForecastResult(
            city="New York", date="2026-01-15", model="gfs",
            temp_high_c=25.0, measure_type="high",
            members=[24.0, 25.0, 26.0],
        )
        event = engine._build_synthetic_event("New York", "2026-01-15", forecast)
        assert event.city == "New York"
        assert len(event.buckets) == 9

    def test_bucket_hit_celsius(self):
        engine = BacktestEngine(strategies=[])
        bucket = TemperatureBucket(
            market_id="b1", question="25°C",
            temp_low=25.0, temp_high=25.0, temp_unit="C",
            yes_price=0.5, no_price=0.5, volume=100.0,
        )
        assert engine._bucket_hit(bucket, 25.4) is True
        assert engine._bucket_hit(bucket, 24.9) is False

    def test_bucket_hit_fahrenheit(self):
        engine = BacktestEngine(strategies=[])
        bucket = TemperatureBucket(
            market_id="b1", question="77°F",
            temp_low=77.0, temp_high=77.0, temp_unit="F",
            yes_price=0.5, no_price=0.5, volume=100.0,
        )
        obs_c = (77.0 - 32) / 1.8
        assert engine._bucket_hit(bucket, obs_c) is True

    def test_bucket_hit_tail_low(self):
        engine = BacktestEngine(strategies=[])
        bucket = TemperatureBucket(
            market_id="b1", question="≤20°C",
            temp_low=-999.0, temp_high=20.0, temp_unit="C",
            yes_price=0.1, no_price=0.9, volume=100.0,
        )
        assert engine._bucket_hit(bucket, 18.0) is True
        assert engine._bucket_hit(bucket, 22.0) is False

    def test_bucket_hit_tail_high(self):
        engine = BacktestEngine(strategies=[])
        bucket = TemperatureBucket(
            market_id="b1", question="≥27°C",
            temp_low=27.0, temp_high=999.0, temp_unit="C",
            yes_price=0.1, no_price=0.9, volume=100.0,
        )
        assert engine._bucket_hit(bucket, 28.0) is True
        assert engine._bucket_hit(bucket, 25.0) is False


class TestBacktestEngineBuildRealEventFromResolution:
    def test_basic(self):
        engine = BacktestEngine(strategies=[])
        forecast = ForecastResult(
            city="New York", date="2026-01-15", model="gfs",
            temp_high_c=25.0, measure_type="high",
            members=[24.0, 25.0, 26.0],
        )
        market = ResolvedMarket(
            question="between 23-24°C",
            token_id="tok12345678901234567890",
            outcome="Yes",
            winning=True,
            yes_price=0.8,
            no_price=0.2,
        )
        ev = ResolvedEvent(
            event_id="ev1",
            title="High temperature in New York",
            slug="nyc-2026-01-15",
            city="New York",
            measure_type="high",
            target_date="2026-01-15",
            markets=[market],
        )
        result = engine._build_real_event_from_resolution(ev, forecast)
        assert result is not None
        assert result.city == "New York"

    def test_no_buckets(self):
        engine = BacktestEngine(strategies=[])
        forecast = ForecastResult(
            city="New York", date="2026-01-15", model="gfs",
            temp_high_c=25.0, measure_type="high",
            members=[24.0, 25.0, 26.0],
        )
        market = ResolvedMarket(
            question="Will it rain?",
            token_id="tok1",
            outcome="No",
            winning=False,
        )
        ev = ResolvedEvent(
            event_id="ev1",
            title="Something",
            slug="s1",
            city="New York",
            measure_type="high",
            target_date="2026-01-15",
            markets=[market],
        )
        result = engine._build_real_event_from_resolution(ev, forecast)
        assert result is None

    def test_clob_price_used(self):
        engine = BacktestEngine(strategies=[])
        forecast = ForecastResult(
            city="New York", date="2026-01-15", model="gfs",
            temp_high_c=25.0, measure_type="high",
            members=[24.0, 25.0, 26.0],
        )
        market = ResolvedMarket(
            question="23°C",
            token_id="tok12345678901234567890",
            outcome="Yes",
            winning=True,
            yes_price=0.4,
            no_price=0.6,
        )
        ev = ResolvedEvent(
            event_id="ev1",
            title="High temp NYC",
            slug="s1",
            city="New York",
            measure_type="high",
            target_date="2026-01-15",
            markets=[market],
        )
        result = engine._build_real_event_from_resolution(ev, forecast)
        assert result is not None
        assert result.buckets[0].yes_price == 0.4

    def test_forecast_fallback_price(self):
        engine = BacktestEngine(strategies=[])
        forecast = ForecastResult(
            city="New York", date="2026-01-15", model="gfs",
            temp_high_c=25.0, measure_type="high",
            members=[24.0, 25.0, 26.0],
        )
        market = ResolvedMarket(
            question="24-25°C",
            token_id="tok12345678901234567890",
            outcome="No",
            winning=False,
            yes_price=0.0,
            no_price=0.0,
        )
        ev = ResolvedEvent(
            event_id="ev1",
            title="High temp NYC",
            slug="s1",
            city="New York",
            measure_type="high",
            target_date="2026-01-15",
            markets=[market],
        )
        result = engine._build_real_event_from_resolution(ev, forecast)
        assert result is not None


class TestBacktestEngineRealBucketHit:
    def test_hit(self):
        engine = BacktestEngine(strategies=[])
        bucket = TemperatureBucket(
            market_id="tok1", question="23°C",
            temp_low=23.0, temp_high=23.0, temp_unit="C",
            yes_price=0.5, no_price=0.5, volume=100.0,
        )
        market = ResolvedMarket(
            question="23°C", token_id="tok1",
            outcome="Yes", winning=True,
        )
        ev = ResolvedEvent(
            event_id="ev1", title="t", slug="s",
            city="NYC", measure_type="high",
            target_date="2026-01-15",
            markets=[market],
        )
        assert engine._real_bucket_hit(ev, bucket) is True

    def test_miss(self):
        engine = BacktestEngine(strategies=[])
        bucket = TemperatureBucket(
            market_id="tok1", question="23°C",
            temp_low=23.0, temp_high=23.0, temp_unit="C",
            yes_price=0.5, no_price=0.5, volume=100.0,
        )
        market = ResolvedMarket(
            question="23°C", token_id="tok1",
            outcome="No", winning=False,
        )
        ev = ResolvedEvent(
            event_id="ev1", title="t", slug="s",
            city="NYC", measure_type="high",
            target_date="2026-01-15",
            markets=[market],
        )
        assert engine._real_bucket_hit(ev, bucket) is False

    def test_no_matching_market(self):
        engine = BacktestEngine(strategies=[])
        bucket = TemperatureBucket(
            market_id="other", question="23°C",
            temp_low=23.0, temp_high=23.0, temp_unit="C",
            yes_price=0.5, no_price=0.5, volume=100.0,
        )
        market = ResolvedMarket(
            question="23°C", token_id="tok1",
            outcome="No", winning=False,
        )
        ev = ResolvedEvent(
            event_id="ev1", title="t", slug="s",
            city="NYC", measure_type="high",
            target_date="2026-01-15",
            markets=[market],
        )
        assert engine._real_bucket_hit(ev, bucket) is False


class TestBacktestEngineGetResolvedTemp:
    def test_celsius(self):
        engine = BacktestEngine(strategies=[])
        market = ResolvedMarket(
            question="between 23-24°C", token_id="tok1",
            outcome="Yes", winning=True,
        )
        ev = ResolvedEvent(
            event_id="ev1", title="t", slug="s",
            city="NYC", measure_type="high",
            target_date="2026-01-15",
            markets=[market],
        )
        temp = engine._get_resolved_temp(ev)
        assert temp == 23.0

    def test_fahrenheit(self):
        engine = BacktestEngine(strategies=[])
        market = ResolvedMarket(
            question="between 75-76°F", token_id="tok1",
            outcome="Yes", winning=True,
        )
        ev = ResolvedEvent(
            event_id="ev1", title="t", slug="s",
            city="NYC", measure_type="high",
            target_date="2026-01-15",
            markets=[market],
        )
        temp = engine._get_resolved_temp(ev)
        assert temp is not None
        expected_c = (75.0 - 32) / 1.8
        assert abs(temp - expected_c) < 0.01

    def test_above_format(self):
        engine = BacktestEngine(strategies=[])
        market = ResolvedMarket(
            question="above 75°F", token_id="tok1",
            outcome="Yes", winning=True,
        )
        ev = ResolvedEvent(
            event_id="ev1", title="t", slug="s",
            city="NYC", measure_type="high",
            target_date="2026-01-15",
            markets=[market],
        )
        temp = engine._get_resolved_temp(ev)
        assert temp is not None

    def test_no_winning_market(self):
        engine = BacktestEngine(strategies=[])
        market = ResolvedMarket(
            question="between 23-24°C", token_id="tok1",
            outcome="No", winning=False,
        )
        ev = ResolvedEvent(
            event_id="ev1", title="t", slug="s",
            city="NYC", measure_type="high",
            target_date="2026-01-15",
            markets=[market],
        )
        temp = engine._get_resolved_temp(ev)
        assert temp is None

    def test_above_celsius(self):
        engine = BacktestEngine(strategies=[])
        market = ResolvedMarket(
            question="above 25°C", token_id="tok1",
            outcome="Yes", winning=True,
        )
        ev = ResolvedEvent(
            event_id="ev1", title="t", slug="s",
            city="NYC", measure_type="high",
            target_date="2026-01-15",
            markets=[market],
        )
        temp = engine._get_resolved_temp(ev)
        assert temp == 25.0


class TestBacktestEngineRunReal:
    @pytest.mark.asyncio
    async def test_no_resolved_events(self):
        engine = BacktestEngine(strategies=[TestDummyStrategy.DummyStrategy()])
        with patch("pm_bot.backtest.engine.RealDataFetcher") as mock_fetcher_cls:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch_resolved_weather_events = AsyncMock(return_value=[])
            mock_fetcher.close = MagicMock()
            mock_fetcher_cls.return_value = mock_fetcher
            result = await engine.run_real()
        assert result == []

    @pytest.mark.asyncio
    async def test_with_resolved_events(self):
        engine = BacktestEngine(
            strategies=[TestDummyStrategy.DummyStrategy()],
            bankroll=100.0, days=90, cities=["New York"],
        )
        forecast = ForecastResult(
            city="New York", date="2026-01-15", model="gfs",
            temp_high_c=25.0, measure_type="high",
            members=[24.0, 25.0, 26.0],
        )
        market = ResolvedMarket(
            question="23°C",
            token_id="tok12345678901234567890",
            outcome="No",
            winning=False,
            yes_price=0.3,
            no_price=0.7,
        )
        ev = ResolvedEvent(
            event_id="ev1",
            title="High temp NYC",
            slug="s1",
            city="New York",
            measure_type="high",
            target_date="2026-01-15",
            markets=[market],
        )
        with patch("pm_bot.backtest.engine.RealDataFetcher") as mock_fetcher_cls:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch_resolved_weather_events = AsyncMock(return_value=[ev])
            mock_fetcher.enrich_events_with_clob_prices = AsyncMock()
            mock_fetcher.prefetch_forecasts = AsyncMock()
            mock_fetcher.get_cached_forecast = MagicMock(return_value=forecast)
            mock_fetcher.close = MagicMock()
            mock_fetcher_cls.return_value = mock_fetcher
            result = await engine.run_real()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_stop_loss(self):
        engine = BacktestEngine(
            strategies=[TestDummyStrategy.ProducingStrategy()],
            bankroll=100.0, days=90, cities=["New York"],
            stop_loss_pct=0.5,
        )
        forecast = ForecastResult(
            city="New York", date="2026-01-15", model="gfs",
            temp_high_c=25.0, measure_type="high",
            members=[24.0, 25.0, 26.0],
        )
        market = ResolvedMarket(
            question="23°C",
            token_id="tok12345678901234567890",
            outcome="No",
            winning=False,
            yes_price=0.3,
            no_price=0.7,
        )
        ev = ResolvedEvent(
            event_id="ev1",
            title="High temp NYC",
            slug="s1",
            city="New York",
            measure_type="high",
            target_date="2026-01-15",
            markets=[market],
        )
        with patch("pm_bot.backtest.engine.RealDataFetcher") as mock_fetcher_cls:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch_resolved_weather_events = AsyncMock(return_value=[ev])
            mock_fetcher.enrich_events_with_clob_prices = AsyncMock()
            mock_fetcher.prefetch_forecasts = AsyncMock()
            mock_fetcher.get_cached_forecast = MagicMock(return_value=forecast)
            mock_fetcher.close = MagicMock()
            mock_fetcher_cls.return_value = mock_fetcher
            result = await engine.run_real()
        assert len(result) == 1
        assert result[0].trades[0].stop_loss_pct == 0.5

    @pytest.mark.asyncio
    async def test_non_compound_mode(self):
        engine = BacktestEngine(
            strategies=[TestDummyStrategy.DummyStrategy()],
            bankroll=100.0, days=90, cities=["New York"],
            compound=False,
        )
        with patch("pm_bot.backtest.engine.RealDataFetcher") as mock_fetcher_cls:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch_resolved_weather_events = AsyncMock(return_value=[])
            mock_fetcher.close = MagicMock()
            mock_fetcher_cls.return_value = mock_fetcher
            result = await engine.run_real()
        assert result == []

    @pytest.mark.asyncio
    async def test_kelly_fraction_override(self):
        engine = BacktestEngine(
            strategies=[TestDummyStrategy.DummyStrategy()],
            kelly_fraction_val=0.5,
        )
        assert engine.kelly_fraction_val == 0.5

    @pytest.mark.asyncio
    async def test_no_forecast_for_event(self):
        engine = BacktestEngine(
            strategies=[TestDummyStrategy.DummyStrategy()],
            bankroll=100.0, days=90, cities=["New York"],
        )
        market = ResolvedMarket(
            question="23°C",
            token_id="tok12345678901234567890",
            outcome="No",
            winning=False,
        )
        ev = ResolvedEvent(
            event_id="ev1",
            title="High temp NYC",
            slug="s1",
            city="New York",
            measure_type="high",
            target_date="2026-01-15",
            markets=[market],
        )
        with patch("pm_bot.backtest.engine.RealDataFetcher") as mock_fetcher_cls:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch_resolved_weather_events = AsyncMock(return_value=[ev])
            mock_fetcher.enrich_events_with_clob_prices = AsyncMock()
            mock_fetcher.prefetch_forecasts = AsyncMock()
            mock_fetcher.get_cached_forecast = MagicMock(return_value=None)
            mock_fetcher.close = MagicMock()
            mock_fetcher_cls.return_value = mock_fetcher
            result = await engine.run_real()
        assert len(result) == 1
        assert len(result[0].trades) == 0


class TestBacktestEngineRun:
    @pytest.mark.asyncio
    async def test_with_empty_strategy(self):
        engine = BacktestEngine(
            strategies=[TestDummyStrategy.DummyStrategy()],
            bankroll=100.0,
            days=1,
            cities=["NYC"],
        )
        with patch("pm_bot.backtest.engine.HistoricalDataFetcher") as mock_fetcher_cls:
            mock_fetcher = MagicMock()
            forecast = ForecastResult(
                city="New York", date="2026-01-15", model="gfs",
                temp_high_c=25.0, measure_type="high",
                members=[25.0, 26.0, 27.0],
            )
            mock_fetcher.fetch_historical_forecasts = AsyncMock(return_value=forecast)
            mock_fetcher.fetch_historical_observations = AsyncMock(return_value=25.0)
            mock_fetcher_cls.return_value = mock_fetcher
            result = await engine.run()
        assert len(result) == 1
        assert result[0].strategy_name == "dummy"
        assert len(result[0].trades) == 0

    @pytest.mark.asyncio
    async def test_non_compound(self):
        engine = BacktestEngine(
            strategies=[TestDummyStrategy.DummyStrategy()],
            bankroll=100.0, days=1, cities=["NYC"],
            compound=False,
        )
        with patch("pm_bot.backtest.engine.HistoricalDataFetcher") as mock_fetcher_cls:
            mock_fetcher = MagicMock()
            forecast = ForecastResult(
                city="New York", date="2026-01-15", model="gfs",
                temp_high_c=25.0, measure_type="high",
                members=[25.0, 26.0, 27.0],
            )
            mock_fetcher.fetch_historical_forecasts = AsyncMock(return_value=forecast)
            mock_fetcher.fetch_historical_observations = AsyncMock(return_value=25.0)
            mock_fetcher_cls.return_value = mock_fetcher
            result = await engine.run()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_no_forecast(self):
        engine = BacktestEngine(
            strategies=[TestDummyStrategy.DummyStrategy()],
            bankroll=100.0, days=1, cities=["NYC"],
        )
        with patch("pm_bot.backtest.engine.HistoricalDataFetcher") as mock_fetcher_cls:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch_historical_forecasts = AsyncMock(return_value=None)
            mock_fetcher.fetch_historical_observations = AsyncMock(return_value=None)
            mock_fetcher_cls.return_value = mock_fetcher
            result = await engine.run()
        assert len(result) == 1
        assert len(result[0].trades) == 0

    @pytest.mark.asyncio
    async def test_with_observation(self):
        engine = BacktestEngine(
            strategies=[TestDummyStrategy.ProducingStrategy()],
            bankroll=100.0, days=1, cities=["NYC"],
        )
        with patch("pm_bot.backtest.engine.HistoricalDataFetcher") as mock_fetcher_cls:
            mock_fetcher = MagicMock()
            forecast = ForecastResult(
                city="New York", date="2026-01-15", model="gfs",
                temp_high_c=25.0, measure_type="high",
                members=[25.0, 26.0, 27.0],
            )
            mock_fetcher.fetch_historical_forecasts = AsyncMock(return_value=forecast)
            mock_fetcher.fetch_historical_observations = AsyncMock(return_value=25.4)
            mock_fetcher_cls.return_value = mock_fetcher
            result = await engine.run()
        assert len(result) == 1
        assert len(result[0].trades) >= 1
