from __future__ import annotations
import pytest

from unittest.mock import AsyncMock, MagicMock, patch

from pm_bot.cli.explain import run_explain, _find_in_events


class TestRunExplain:
    @patch("pm_bot.cli.explain.fetch_weather_events", new_callable=AsyncMock)
    @patch("pm_bot.cli.explain._parse_event", return_value=None)
    @patch("pm_bot.cli.explain.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_market_not_found(self, mock_client_cls, mock_parse, mock_events):
        mock_events.return_value = []
        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        await run_explain(market_id="nonexistent")

    @patch("pm_bot.cli.explain.fetch_forecast", new_callable=AsyncMock)
    @patch("pm_bot.cli.explain.fetch_weather_events", new_callable=AsyncMock)
    @patch("pm_bot.cli.explain._parse_event")
    @patch("pm_bot.cli.explain.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_market_found_direct(self, mock_client_cls, mock_parse, mock_events, mock_forecast):
        from pm_bot.models.market import WeatherEvent, TemperatureBucket
        ev = WeatherEvent(
            event_id="ev1", title="NYC High Temp 2026-01-15", slug="nyc",
            city="New York", date="2026-01-15", measure_type="high",
            buckets=[TemperatureBucket(
                market_id="m1", question="23C", temp_low=23.0, temp_high=23.0,
                temp_unit="C", yes_price=0.15, no_price=0.85, volume=500.0,
            )],
        )
        mock_parse.return_value = ev
        mock_events.return_value = []
        mock_forecast.return_value = None

        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "ev1"}
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        await run_explain(market_id="ev1")


class TestFindInEvents:
    @patch("pm_bot.cli.explain.fetch_weather_events", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_find_by_event_id(self, mock_events):
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
        mock_client = AsyncMock()
        result = await _find_in_events(mock_client, "ev1")
        assert result is not None
        assert result.event_id == "ev1"

    @patch("pm_bot.cli.explain.fetch_weather_events", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_find_by_market_id(self, mock_events):
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
        mock_client = AsyncMock()
        result = await _find_in_events(mock_client, "m1")
        assert result is not None

    @patch("pm_bot.cli.explain.fetch_weather_events", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_not_found(self, mock_events):
        mock_events.return_value = []
        mock_client = AsyncMock()
        result = await _find_in_events(mock_client, "nonexistent")
        assert result is None
