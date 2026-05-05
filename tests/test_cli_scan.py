from __future__ import annotations
import pytest

from unittest.mock import AsyncMock, patch

from pm_bot.cli.scan import run_scan, _resolve_cities, _resolve_strategies


class TestResolveCities:
    def test_all_cities(self):
        result = _resolve_cities(None, True)
        assert result == set()

    def test_cities_str(self):
        result = _resolve_cities("NYC,HK", False)
        assert "New York" in result
        assert "Hong Kong" in result

    def test_default_cities(self):
        result = _resolve_cities(None, False)
        assert len(result) > 0

    def test_single_city(self):
        result = _resolve_cities("NYC", False)
        assert "New York" in result


class TestResolveStrategies:
    def test_all_strategies(self):
        result = _resolve_strategies("all")
        assert len(result) > 0

    def test_specific_strategy(self):
        result = _resolve_strategies("gopfan2")
        assert len(result) == 1
        assert result[0][0] == "gopfan2"

    def test_unknown_strategy(self):
        result = _resolve_strategies("nonexistent")
        assert result == []


class TestRunScan:
    @pytest.mark.asyncio
    @patch("pm_bot.cli.scan.render_recommendations")
    @patch("pm_bot.cli.scan.fetch_weather_events", new_callable=AsyncMock)
    @patch("pm_bot.cli.scan.fetch_forecast", new_callable=AsyncMock)
    async def test_no_events(self, mock_forecast, mock_events, mock_render):
        mock_events.return_value = []
        await run_scan()
        mock_render.assert_not_called()

    @patch("pm_bot.cli.scan.render_recommendations")
    @patch("pm_bot.cli.scan.fetch_weather_events", new_callable=AsyncMock)
    @patch("pm_bot.cli.scan.fetch_forecast", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_with_events(self, mock_forecast, mock_events, mock_render):
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
        mock_forecast.return_value = None
        await run_scan()
        mock_render.assert_called_once()

    @patch("pm_bot.cli.scan.render_verbose")
    @patch("pm_bot.cli.scan.fetch_weather_events", new_callable=AsyncMock)
    @patch("pm_bot.cli.scan.fetch_forecast", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_verbose_mode(self, mock_forecast, mock_events, mock_render):
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
        mock_forecast.return_value = None
        await run_scan(verbose=True)
        mock_render.assert_called_once()

    @patch("pm_bot.cli.scan.filter_recommendations", return_value=[])
    @patch("pm_bot.cli.scan.fetch_observation", new_callable=AsyncMock)
    @patch("pm_bot.cli.scan.render_recommendations")
    @patch("pm_bot.cli.scan.fetch_weather_events", new_callable=AsyncMock)
    @patch("pm_bot.cli.scan.fetch_forecast", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_observed_filter(self, mock_forecast, mock_events, mock_render, mock_obs, mock_filter):
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
        mock_forecast.return_value = None
        mock_obs.return_value = None
        await run_scan(observed=True)
        mock_render.assert_called_once()
