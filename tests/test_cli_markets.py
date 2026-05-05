from __future__ import annotations
import pytest

from unittest.mock import AsyncMock, patch

from pm_bot.cli.markets import run_markets


class TestRunMarkets:
    @patch("pm_bot.cli.markets.render_events")
    @patch("pm_bot.cli.markets.fetch_weather_events", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_default(self, mock_events, mock_render):
        mock_events.return_value = []
        await run_markets()
        mock_render.assert_called_once_with([])

    @patch("pm_bot.cli.markets.render_events")
    @patch("pm_bot.cli.markets.fetch_weather_events", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_with_city_filter(self, mock_events, mock_render):
        from pm_bot.models.market import WeatherEvent
        ev1 = WeatherEvent(event_id="ev1", title="NYC", slug="nyc", city="New York",
                           date="2026-01-15", measure_type="high", buckets=[])
        ev2 = WeatherEvent(event_id="ev2", title="London", slug="london", city="London",
                           date="2026-01-15", measure_type="high", buckets=[])
        mock_events.return_value = [ev1, ev2]
        await run_markets(cities_str="NYC")
        assert len(mock_render.call_args[0][0]) == 1

    @patch("pm_bot.cli.markets.render_events")
    @patch("pm_bot.cli.markets.fetch_weather_events", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_all_cities(self, mock_events, mock_render):
        from pm_bot.models.market import WeatherEvent
        ev1 = WeatherEvent(event_id="ev1", title="NYC", slug="nyc", city="New York",
                           date="2026-01-15", measure_type="high", buckets=[])
        ev2 = WeatherEvent(event_id="ev2", title="London", slug="london", city="London",
                           date="2026-01-15", measure_type="high", buckets=[])
        mock_events.return_value = [ev1, ev2]
        await run_markets(all_cities=True)
        assert len(mock_render.call_args[0][0]) == 2

    @patch("pm_bot.cli.markets.render_events")
    @patch("pm_bot.cli.markets.fetch_weather_events", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_include_closed(self, mock_events, mock_render):
        mock_events.return_value = []
        await run_markets(include_closed=True)
        mock_events.assert_called_once()

    @patch("pm_bot.cli.markets.render_events")
    @patch("pm_bot.cli.markets.fetch_weather_events", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_no_events(self, mock_events, mock_render):
        mock_events.return_value = []
        await run_markets()
