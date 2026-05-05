from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pm_bot.core.sources.nws import fetch_nws_forecast, _parse_nws_hourly


class TestFetchNwsForecast:
    @pytest.mark.asyncio
    async def test_unknown_city(self):
        client = AsyncMock()
        result = await fetch_nws_forecast(client, "UnknownCity")
        assert result is None

    @pytest.mark.asyncio
    async def test_points_api_error(self):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=httpx.HTTPError("fail"))
        result = await fetch_nws_forecast(client, "New York")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_hourly_url(self):
        client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = {"properties": {}}
        resp.raise_for_status = MagicMock()
        client.get = AsyncMock(return_value=resp)
        result = await fetch_nws_forecast(client, "New York")
        assert result is None

    @pytest.mark.asyncio
    async def test_hourly_api_error(self):
        client = AsyncMock()
        points_resp = MagicMock()
        points_resp.json.return_value = {"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/NYC/1,1/forecast/hourly"}}
        points_resp.raise_for_status = MagicMock()

        client.get = AsyncMock(side_effect=[points_resp, httpx.HTTPError("fail")])
        result = await fetch_nws_forecast(client, "New York")
        assert result is None

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        client = AsyncMock()
        points_resp = MagicMock()
        points_resp.json.return_value = {"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/NYC/1,1/forecast/hourly"}}
        points_resp.raise_for_status = MagicMock()

        hourly_resp = MagicMock()
        hourly_resp.json.return_value = {
            "properties": {
                "periods": [
                    {"temperature": 75},
                    {"temperature": 80},
                    {"temperature": 72},
                ]
            }
        }
        hourly_resp.raise_for_status = MagicMock()

        client.get = AsyncMock(side_effect=[points_resp, hourly_resp])
        result = await fetch_nws_forecast(client, "New York")
        assert result is not None
        assert result["source"] == "nws"
        assert result["temp_high_c"] > 0

    @pytest.mark.asyncio
    async def test_nyc_alias(self):
        client = AsyncMock()
        from pm_bot.models.config import CITY_COORDS
        assert "NYC" in CITY_COORDS
        client.get = AsyncMock(side_effect=httpx.HTTPError("fail"))
        result = await fetch_nws_forecast(client, "NYC")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        from pm_bot.core.sources.nws import _nws_cache
        _nws_cache["nws:New York"] = {"city": "New York", "source": "nws", "temp_high_c": 30.0}
        client = AsyncMock()
        result = await fetch_nws_forecast(client, "New York")
        assert result is not None
        assert result["temp_high_c"] == 30.0
        client.get.assert_not_called()
        _nws_cache.pop("nws:New York", None)


class TestParseNwsHourly:
    def test_basic_periods(self):
        data = {
            "properties": {
                "periods": [
                    {"temperature": 75},
                    {"temperature": 80},
                    {"temperature": 72},
                ]
            }
        }
        result = _parse_nws_hourly(data, "NYC", "2026-01-15")
        assert result is not None
        assert result["temp_high_c"] == (80 - 32) / 1.8

    def test_empty_periods(self):
        data = {"properties": {"periods": []}}
        result = _parse_nws_hourly(data, "NYC", "2026-01-15")
        assert result is None

    def test_no_periods_key(self):
        data = {"properties": {}}
        result = _parse_nws_hourly(data, "NYC", "2026-01-15")
        assert result is None

    def test_all_none_temps(self):
        data = {
            "properties": {
                "periods": [
                    {"temperature": None},
                    {"temperature": None},
                ]
            }
        }
        result = _parse_nws_hourly(data, "NYC", "2026-01-15")
        assert result is None
