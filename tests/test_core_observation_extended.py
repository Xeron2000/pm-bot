from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pm_bot.core.observation import (
    ObservedTemp,
    fetch_metar_obs,
    fetch_previous_metar,
    fetch_observation,
    fetch_observed_high,
    should_filter_bucket,
    filter_recommendations,
    resolve_icao_from_description,
    get_icao,
    CITY_ICAO,
    CITY_TZ,
    AWC_URL,
)
from pm_bot.models.market import (
    TemperatureBucket,
    WeatherEvent,
    Recommendation,
)


class TestFetchMetarObs:
    @pytest.mark.asyncio
    async def test_success(self):
        client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = [{"temp": "25.0", "obsTime": "2026-01-15T18:00:00Z"}]
        resp.raise_for_status = MagicMock()
        client.get = AsyncMock(return_value=resp)
        result = await fetch_metar_obs(client, "KLGA")
        assert result is not None
        assert result["temp"] == "25.0"

    @pytest.mark.asyncio
    async def test_empty_data(self):
        client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = []
        resp.raise_for_status = MagicMock()
        client.get = AsyncMock(return_value=resp)
        result = await fetch_metar_obs(client, "KLGA")
        assert result is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=httpx.HTTPError("fail"))
        result = await fetch_metar_obs(client, "KLGA")
        assert result is None


class TestFetchPreviousMetar:
    @pytest.mark.asyncio
    async def test_success(self):
        client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = [
            {"temp": "25.0", "obsTime": "2026-01-15T18:00:00Z"},
            {"temp": "23.0", "obsTime": "2026-01-15T17:00:00Z"},
        ]
        resp.raise_for_status = MagicMock()
        client.get = AsyncMock(return_value=resp)
        result = await fetch_previous_metar(client, "KLGA")
        assert result is not None
        assert result["temp"] == "23.0"

    @pytest.mark.asyncio
    async def test_single_entry_returns_none(self):
        client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = [{"temp": "25.0"}]
        resp.raise_for_status = MagicMock()
        client.get = AsyncMock(return_value=resp)
        result = await fetch_previous_metar(client, "KLGA")
        assert result is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=httpx.HTTPError("fail"))
        result = await fetch_previous_metar(client, "KLGA")
        assert result is None


class TestFetchObservation:
    @pytest.mark.asyncio
    async def test_unknown_city(self):
        client = AsyncMock()
        result = await fetch_observation(client, "Atlantis")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_metar(self):
        client = AsyncMock()
        with patch("pm_bot.core.observation.fetch_metar_obs", new_callable=AsyncMock, return_value=None):
            result = await fetch_observation(client, "New York")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_temp_field(self):
        metar = {"obsTime": "2026-01-15T18:00:00Z"}
        with patch("pm_bot.core.observation.fetch_metar_obs", new_callable=AsyncMock, return_value=metar):
            with patch("pm_bot.core.observation.fetch_previous_metar", new_callable=AsyncMock, return_value=None):
                result = await fetch_observation(AsyncMock(), "New York")
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_temp(self):
        metar = {"temp": "N/A", "obsTime": "2026-01-15T18:00:00Z"}
        with patch("pm_bot.core.observation.fetch_metar_obs", new_callable=AsyncMock, return_value=metar):
            with patch("pm_bot.core.observation.fetch_previous_metar", new_callable=AsyncMock, return_value=None):
                result = await fetch_observation(AsyncMock(), "New York")
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_observation(self):
        metar = {"temp": "25.0", "obsTime": "2026-01-15T18:00:00Z"}
        prev = {"temp": "24.0"}
        with patch("pm_bot.core.observation.fetch_metar_obs", new_callable=AsyncMock, return_value=metar):
            with patch("pm_bot.core.observation.fetch_previous_metar", new_callable=AsyncMock, return_value=prev):
                result = await fetch_observation(AsyncMock(), "New York")
        assert result is not None
        assert result.observed_c == 25.0
        assert result.anomaly_detected is False

    @pytest.mark.asyncio
    async def test_spike_detected(self):
        metar = {"temp": "28.0", "obsTime": "2026-01-15T18:00:00Z"}
        prev = {"temp": "24.0"}
        with patch("pm_bot.core.observation.fetch_metar_obs", new_callable=AsyncMock, return_value=metar):
            with patch("pm_bot.core.observation.fetch_previous_metar", new_callable=AsyncMock, return_value=prev):
                result = await fetch_observation(AsyncMock(), "New York")
        assert result is not None
        assert result.anomaly_detected is True

    @pytest.mark.asyncio
    async def test_prev_invalid_temp_no_anomaly(self):
        metar = {"temp": "28.0", "obsTime": "2026-01-15T18:00:00Z"}
        prev = {"temp": "N/A"}
        with patch("pm_bot.core.observation.fetch_metar_obs", new_callable=AsyncMock, return_value=metar):
            with patch("pm_bot.core.observation.fetch_previous_metar", new_callable=AsyncMock, return_value=prev):
                result = await fetch_observation(AsyncMock(), "New York")
        assert result is not None
        assert result.anomaly_detected is False

    @pytest.mark.asyncio
    async def test_no_prev_no_anomaly(self):
        metar = {"temp": "25.0", "obsTime": "2026-01-15T18:00:00Z"}
        with patch("pm_bot.core.observation.fetch_metar_obs", new_callable=AsyncMock, return_value=metar):
            with patch("pm_bot.core.observation.fetch_previous_metar", new_callable=AsyncMock, return_value=None):
                result = await fetch_observation(AsyncMock(), "New York")
        assert result is not None
        assert result.anomaly_detected is False

    @pytest.mark.asyncio
    async def test_invalid_obs_time(self):
        metar = {"temp": "25.0", "obsTime": "invalid-date"}
        with patch("pm_bot.core.observation.fetch_metar_obs", new_callable=AsyncMock, return_value=metar):
            with patch("pm_bot.core.observation.fetch_previous_metar", new_callable=AsyncMock, return_value=None):
                result = await fetch_observation(AsyncMock(), "New York")
        assert result is not None
        assert result.obs_time_utc is not None

    @pytest.mark.asyncio
    async def test_measure_type_low(self):
        metar = {"temp": "5.0", "obsTime": "2026-01-15T06:00:00Z"}
        with patch("pm_bot.core.observation.fetch_metar_obs", new_callable=AsyncMock, return_value=metar):
            with patch("pm_bot.core.observation.fetch_previous_metar", new_callable=AsyncMock, return_value=None):
                result = await fetch_observation(AsyncMock(), "New York", measure_type="low")
        assert result is not None
        assert result.measure_type == "low"


class TestFetchObservedHigh:
    @pytest.mark.asyncio
    async def test_delegates_to_fetch_observation(self):
        metar = {"temp": "25.0", "obsTime": "2026-01-15T18:00:00Z"}
        with patch("pm_bot.core.observation.fetch_metar_obs", new_callable=AsyncMock, return_value=metar):
            with patch("pm_bot.core.observation.fetch_previous_metar", new_callable=AsyncMock, return_value=None):
                result = await fetch_observed_high(AsyncMock(), "New York")
        assert result is not None
        assert result.measure_type == "high"
