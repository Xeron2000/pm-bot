from __future__ import annotations

import pytest

from unittest.mock import AsyncMock, MagicMock, patch

from pm_bot.cli.watch import (
    run_watch,
    _resolve_cities,
    _resolve_strategies,
    _setup_logging,
)


class TestResolveCities:
    def test_cities_str(self):
        result = _resolve_cities("NYC,HK")
        assert "New York" in result
        assert "Hong Kong" in result

    def test_default(self):
        result = _resolve_cities(None)
        assert len(result) > 0

    def test_single_city(self):
        result = _resolve_cities("NYC")
        assert "New York" in result

    def test_whitespace_handling(self):
        result = _resolve_cities(" NYC , HK ")
        assert "New York" in result
        assert "Hong Kong" in result


class TestResolveStrategies:
    def test_all(self):
        result = _resolve_strategies("all")
        assert len(result) > 0

    def test_specific(self):
        result = _resolve_strategies("gopfan2")
        assert result[0][0] == "gopfan2"

    def test_unknown(self):
        result = _resolve_strategies("nonexistent")
        assert len(result) > 0


class TestSetupLogging:
    def test_debug(self):
        _setup_logging(debug=True)

    def test_no_debug(self):
        _setup_logging(debug=False)


class TestRunWatch:
    @pytest.mark.asyncio
    @patch("pm_bot.cli.watch.load_config", return_value={})
    @patch("pm_bot.cli.watch.fetch_weather_events", new_callable=AsyncMock)
    async def test_no_events(self, mock_events, mock_config):
        mock_events.return_value = []
        with patch("pm_bot.cli.watch._resolve_cities", return_value={"New York"}):
            with patch("pm_bot.cli.watch._resolve_strategies", return_value=[]):
                with patch("asyncio.sleep", new_callable=AsyncMock, side_effect=KeyboardInterrupt):
                    await run_watch(interval=1, use_ws=False)

    @pytest.mark.asyncio
    @patch("pm_bot.cli.watch.load_config", return_value={})
    @patch("pm_bot.cli.watch.render_recommendations")
    @patch("pm_bot.cli.watch.fetch_forecast", new_callable=AsyncMock, return_value=None)
    @patch("pm_bot.cli.watch.fetch_weather_events", new_callable=AsyncMock)
    async def test_with_events_no_ws(self, mock_events, mock_fc, mock_render, mock_config):
        from pm_bot.models.market import WeatherEvent, TemperatureBucket
        ev = WeatherEvent(
            event_id="ev1", title="Test", slug="test", city="New York",
            date="2026-01-15", measure_type="high",
            buckets=[TemperatureBucket(
                market_id="m1", question="23C", temp_low=23.0, temp_high=23.0,
                temp_unit="C", yes_price=0.15, no_price=0.85, volume=500.0,
            )],
        )
        mock_events.return_value = [ev]
        with patch("pm_bot.cli.watch._resolve_cities", return_value={"New York"}):
            with patch("pm_bot.cli.watch._resolve_strategies", return_value=[]):
                with patch("asyncio.sleep", new_callable=AsyncMock, side_effect=KeyboardInterrupt):
                    await run_watch(interval=1, use_ws=False, all_cities=True)

    @pytest.mark.asyncio
    @patch("pm_bot.cli.watch.load_config", return_value={})
    @patch("pm_bot.cli.watch.render_recommendations")
    @patch("pm_bot.cli.watch.fetch_forecast", new_callable=AsyncMock, return_value=None)
    @patch("pm_bot.cli.watch.fetch_weather_events", new_callable=AsyncMock)
    async def test_with_events_city_filter(self, mock_events, mock_fc, mock_render, mock_config):
        from pm_bot.models.market import WeatherEvent, TemperatureBucket
        ev = WeatherEvent(
            event_id="ev1", title="Test", slug="test", city="New York",
            date="2026-01-15", measure_type="high",
            buckets=[TemperatureBucket(
                market_id="m1", question="23C", temp_low=23.0, temp_high=23.0,
                temp_unit="C", yes_price=0.15, no_price=0.85, volume=500.0,
            )],
        )
        mock_events.return_value = [ev]
        with patch("asyncio.sleep", new_callable=AsyncMock, side_effect=KeyboardInterrupt):
            await run_watch(interval=1, use_ws=False, cities_str="NYC")

    @pytest.mark.asyncio
    @patch("pm_bot.cli.watch.load_config", return_value={})
    @patch("pm_bot.cli.watch.render_recommendations")
    @patch("pm_bot.cli.watch.fetch_forecast", new_callable=AsyncMock, return_value=None)
    @patch("pm_bot.cli.watch.fetch_weather_events", new_callable=AsyncMock)
    async def test_with_observed_filter(self, mock_events, mock_fc, mock_render, mock_config):
        from pm_bot.models.market import WeatherEvent, TemperatureBucket
        ev = WeatherEvent(
            event_id="ev1", title="Test", slug="test", city="New York",
            date="2026-01-15", measure_type="high",
            buckets=[TemperatureBucket(
                market_id="m1", question="23C", temp_low=23.0, temp_high=23.0,
                temp_unit="C", yes_price=0.15, no_price=0.85, volume=500.0,
            )],
        )
        mock_events.return_value = [ev]
        with patch("pm_bot.cli.watch.fetch_observation", new_callable=AsyncMock, return_value=None):
            with patch("asyncio.sleep", new_callable=AsyncMock, side_effect=KeyboardInterrupt):
                await run_watch(interval=1, use_ws=False, observed=True, cities_str="NYC")

    @pytest.mark.asyncio
    @patch("pm_bot.cli.watch.load_config", return_value={})
    @patch("pm_bot.cli.watch.render_recommendations")
    @patch("pm_bot.cli.watch.fetch_forecast", new_callable=AsyncMock)
    @patch("pm_bot.cli.watch.fetch_weather_events", new_callable=AsyncMock)
    async def test_with_forecast_and_ws(self, mock_events, mock_fc, mock_render, mock_config):
        from pm_bot.models.market import WeatherEvent, TemperatureBucket, ForecastResult
        ev = WeatherEvent(
            event_id="ev1", title="Test", slug="test", city="New York",
            date="2026-01-15", measure_type="high",
            buckets=[TemperatureBucket(
                market_id="m1", question="23C", temp_low=23.0, temp_high=23.0,
                temp_unit="C", yes_price=0.15, no_price=0.85, volume=500.0,
            )],
        )
        mock_events.return_value = [ev]
        fc = ForecastResult(city="New York", date="2026-01-15", model="gfs",
                            temp_high_c=23.0, members=[23.0])
        mock_fc.return_value = fc
        mock_ws_client = MagicMock()
        mock_ws_client.connect = AsyncMock()
        mock_ws_client.subscribe = AsyncMock()
        mock_ws_client.updates = AsyncMock()
        mock_ws_client.stop = MagicMock()
        with patch("pm_bot.cli.watch.MarketWsClient", return_value=mock_ws_client):
            with patch("asyncio.sleep", new_callable=AsyncMock, side_effect=KeyboardInterrupt):
                with patch("asyncio.create_task", return_value=MagicMock()):
                    with patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=KeyboardInterrupt):
                        await run_watch(interval=1, use_ws=True, cities_str="NYC")

    @pytest.mark.asyncio
    @patch("pm_bot.cli.watch.load_config", return_value={})
    @patch("pm_bot.cli.watch.render_recommendations")
    @patch("pm_bot.cli.watch.fetch_forecast", new_callable=AsyncMock, return_value=None)
    @patch("pm_bot.cli.watch.fetch_weather_events", new_callable=AsyncMock)
    async def test_with_station_and_city_forecast(self, mock_events, mock_fc, mock_render, mock_config):
        from pm_bot.models.market import WeatherEvent, TemperatureBucket, ForecastResult
        ev = WeatherEvent(
            event_id="ev1", title="Test", slug="test", city="New York",
            date="2026-01-15", measure_type="high",
            buckets=[TemperatureBucket(
                market_id="m1", question="23C", temp_low=23.0, temp_high=23.0,
                temp_unit="C", yes_price=0.15, no_price=0.85, volume=500.0,
            )],
        )
        mock_events.return_value = [ev]
        afc = ForecastResult(city="New York", date="2026-01-15", model="gfs",
                             temp_high_c=24.0, members=[24.0])
        with patch("pm_bot.cli.watch.get_station_for_city", return_value={"lat": 40.7, "lon": -74.0}):
            with patch("pm_bot.cli.trade.fetch_forecast_at", new_callable=AsyncMock, return_value=afc):
                with patch("pm_bot.models.config.CITY_COORDS", {"New York": (40.7, -74.0)}):
                    with patch("asyncio.sleep", new_callable=AsyncMock, side_effect=KeyboardInterrupt):
                        await run_watch(interval=1, use_ws=False, cities_str="NYC")

    @pytest.mark.asyncio
    @patch("pm_bot.cli.watch.load_config", return_value={})
    @patch("pm_bot.cli.watch.render_recommendations")
    @patch("pm_bot.cli.watch.fetch_forecast", new_callable=AsyncMock, return_value=None)
    @patch("pm_bot.cli.watch.fetch_weather_events", new_callable=AsyncMock)
    async def test_edge_override(self, mock_events, mock_fc, mock_render, mock_config):
        from pm_bot.models.market import WeatherEvent, TemperatureBucket
        ev = WeatherEvent(
            event_id="ev1", title="Test", slug="test", city="New York",
            date="2026-01-15", measure_type="high",
            buckets=[TemperatureBucket(
                market_id="m1", question="23C", temp_low=23.0, temp_high=23.0,
                temp_unit="C", yes_price=0.15, no_price=0.85, volume=500.0,
            )],
        )
        mock_events.return_value = [ev]
        with patch("asyncio.sleep", new_callable=AsyncMock, side_effect=KeyboardInterrupt):
            await run_watch(interval=1, use_ws=False, edge_override=0.15, cities_str="NYC")

    @pytest.mark.asyncio
    @patch("pm_bot.cli.watch.load_config", return_value={})
    @patch("pm_bot.cli.watch.fetch_weather_events", new_callable=AsyncMock)
    async def test_keyboard_interrupt(self, mock_events, mock_config):
        mock_events.return_value = []
        with patch("asyncio.sleep", new_callable=AsyncMock, side_effect=KeyboardInterrupt):
            await run_watch(interval=1, use_ws=False)
