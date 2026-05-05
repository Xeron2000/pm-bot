from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pm_bot.core.weather import bucket_probability_numpy, fetch_forecast
from pm_bot.models.market import ForecastResult


class TestFetchForecast:
    @pytest.fixture
    def _clear_cache(self):
        from pm_bot.core.weather import _forecast_cache
        _forecast_cache.clear()

    @pytest.mark.asyncio
    async def test_unknown_city_returns_none(self, _clear_cache):
        client = AsyncMock()
        result = await fetch_forecast(client, "UnknownCity123")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_hit(self, _clear_cache):
        from pm_bot.core.weather import _forecast_cache
        cached = ForecastResult(
            city="New York", date="", model="gfs_seamless",
            temp_high_c=25.0, measure_type="high", members=[25.0],
        )
        _forecast_cache["New York:gfs_seamless:high"] = cached
        client = AsyncMock()
        result = await fetch_forecast(client, "New York")
        assert result is cached
        client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_api_error_returns_none(self, _clear_cache):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=httpx.HTTPError("fail"))
        result = await fetch_forecast(client, "New York")
        assert result is None

    @pytest.mark.asyncio
    async def test_successful_fetch_no_ensemble(self, _clear_cache):
        client = AsyncMock()
        main_resp = MagicMock()
        main_resp.json.return_value = {
            "daily": {"temperature_2m_max": [25.0], "temperature_2m_min": [15.0]}
        }
        main_resp.raise_for_status = MagicMock()

        ens_resp = MagicMock()
        ens_resp.json.return_value = {"daily": {}}
        ens_resp.raise_for_status = MagicMock()

        client.get = AsyncMock(side_effect=[main_resp, ens_resp])
        result = await fetch_forecast(client, "New York")
        assert result is not None
        assert result.temp_high_c == 25.0
        assert result.members == []

    @pytest.mark.asyncio
    async def test_successful_fetch_with_ensemble(self, _clear_cache):
        client = AsyncMock()
        main_resp = MagicMock()
        main_resp.json.return_value = {
            "daily": {"temperature_2m_max": [25.0]}
        }
        main_resp.raise_for_status = MagicMock()

        ens_daily = {"temperature_2m_max_member01": [24.0], "temperature_2m_max_member02": [26.0]}
        ens_resp = MagicMock()
        ens_resp.json.return_value = {"daily": ens_daily}
        ens_resp.raise_for_status = MagicMock()

        client.get = AsyncMock(side_effect=[main_resp, ens_resp])
        result = await fetch_forecast(client, "New York")
        assert result is not None
        assert 24.0 in result.members
        assert 26.0 in result.members

    @pytest.mark.asyncio
    async def test_ensemble_failure_still_returns_main(self, _clear_cache):
        client = AsyncMock()
        main_resp = MagicMock()
        main_resp.json.return_value = {
            "daily": {"temperature_2m_max": [25.0]}
        }
        main_resp.raise_for_status = MagicMock()

        client.get = AsyncMock(side_effect=[main_resp, httpx.HTTPError("ens fail")])
        result = await fetch_forecast(client, "New York")
        assert result is not None
        assert result.temp_high_c == 25.0

    @pytest.mark.asyncio
    async def test_low_measure_type(self, _clear_cache):
        client = AsyncMock()
        main_resp = MagicMock()
        main_resp.json.return_value = {
            "daily": {"temperature_2m_max": [25.0], "temperature_2m_min": [10.0]}
        }
        main_resp.raise_for_status = MagicMock()

        ens_resp = MagicMock()
        ens_resp.json.return_value = {"daily": {}}
        ens_resp.raise_for_status = MagicMock()

        client.get = AsyncMock(side_effect=[main_resp, ens_resp])
        result = await fetch_forecast(client, "New York", measure_type="low")
        assert result is not None
        assert result.measure_type == "low"

    @pytest.mark.asyncio
    async def test_result_cached(self, _clear_cache):
        from pm_bot.core.weather import _forecast_cache
        client = AsyncMock()
        main_resp = MagicMock()
        main_resp.json.return_value = {
            "daily": {"temperature_2m_max": [25.0]}
        }
        main_resp.raise_for_status = MagicMock()

        ens_resp = MagicMock()
        ens_resp.json.return_value = {"daily": {}}
        ens_resp.raise_for_status = MagicMock()

        client.get = AsyncMock(side_effect=[main_resp, ens_resp])
        result = await fetch_forecast(client, "New York")
        assert "New York:gfs_seamless:high" in _forecast_cache

    @pytest.mark.asyncio
    async def test_empty_temp_list(self, _clear_cache):
        client = AsyncMock()
        main_resp = MagicMock()
        main_resp.json.return_value = {
            "daily": {"temperature_2m_max": []}
        }
        main_resp.raise_for_status = MagicMock()

        ens_resp = MagicMock()
        ens_resp.json.return_value = {"daily": {}}
        ens_resp.raise_for_status = MagicMock()

        client.get = AsyncMock(side_effect=[main_resp, ens_resp])
        result = await fetch_forecast(client, "New York")
        assert result is not None
        assert result.temp_high_c == 0.0

    @pytest.mark.asyncio
    async def test_non_numeric_temp_treated_as_zero(self, _clear_cache):
        client = AsyncMock()
        main_resp = MagicMock()
        main_resp.json.return_value = {
            "daily": {"temperature_2m_max": ["N/A"]}
        }
        main_resp.raise_for_status = MagicMock()

        ens_resp = MagicMock()
        ens_resp.json.return_value = {"daily": {}}
        ens_resp.raise_for_status = MagicMock()

        client.get = AsyncMock(side_effect=[main_resp, ens_resp])
        result = await fetch_forecast(client, "New York")
        assert result is not None
        assert result.temp_high_c == 0.0

    @pytest.mark.asyncio
    async def test_nyc_alias_coords(self, _clear_cache):
        from pm_bot.models.config import CITY_COORDS
        assert "NYC" in CITY_COORDS
        client = AsyncMock()
        main_resp = MagicMock()
        main_resp.json.return_value = {"daily": {"temperature_2m_max": [20.0]}}
        main_resp.raise_for_status = MagicMock()
        ens_resp = MagicMock()
        ens_resp.json.return_value = {"daily": {}}
        ens_resp.raise_for_status = MagicMock()
        client.get = AsyncMock(side_effect=[main_resp, ens_resp])
        result = await fetch_forecast(client, "NYC")
        assert result is not None


class TestBucketProbabilityEdgeCases:
    def test_no_members_uses_erf(self):
        f = ForecastResult(
            city="NYC", date="2026-01-15", model="gfs",
            temp_high_c=25.0, measure_type="high", members=[],
        )
        prob = bucket_probability_numpy(f, 25.0, 25.0, "C")
        assert 0.0 <= prob <= 1.0
        assert prob > 0

    def test_no_members_low_std_default(self):
        f = ForecastResult(
            city="NYC", date="2026-01-15", model="gfs",
            temp_high_c=25.0, measure_type="high", members=[25.0],
        )
        assert f.std == 0.0
        prob = bucket_probability_numpy(f, 25.0, 25.0, "C")
        assert 0.0 <= prob <= 1.0

    def test_f_no_members(self):
        f = ForecastResult(
            city="Miami", date="2026-06-15", model="gfs",
            temp_high_c=33.0, measure_type="high", members=[],
        )
        prob = bucket_probability_numpy(f, 90.0, 92.0, "F")
        assert 0.0 <= prob <= 1.0
