from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pm_bot.core.sources.metar import fetch_metar, _parse_temp_from_raw, get_icao_for_city


class TestFetchMetar:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        from pm_bot.core.sources.metar import _metar_cache
        _metar_cache.clear()

    @pytest.mark.asyncio
    async def test_invalid_icao_empty(self):
        client = AsyncMock()
        result = await fetch_metar(client, "")
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_icao_wrong_length(self):
        client = AsyncMock()
        result = await fetch_metar(client, "KL")
        assert result is None

    @pytest.mark.asyncio
    async def test_http_error(self):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=httpx.HTTPError("fail"))
        result = await fetch_metar(client, "KLGA")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_data(self):
        client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = []
        resp.raise_for_status = MagicMock()
        client.get = AsyncMock(return_value=resp)
        result = await fetch_metar(client, "KLGA")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_temp_in_data(self):
        client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = [{}]
        resp.raise_for_status = MagicMock()
        client.get = AsyncMock(return_value=resp)
        result = await fetch_metar(client, "KLGA")
        assert result is None

    @pytest.mark.asyncio
    async def test_raw_text_fallback(self):
        client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = [{"rawText": "KLGA 151800Z 18010KT 10SM FEW040 25/18 A3002"}]
        resp.raise_for_status = MagicMock()
        client.get = AsyncMock(return_value=resp)
        with patch("pm_bot.core.sources.metar._metar_cache", {}):
            result = await fetch_metar(client, "KLGA")
        assert result is not None
        assert result["temp_c"] == 25.0

    @pytest.mark.asyncio
    async def test_raw_text_negative_temp(self):
        client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = [{"rawText": "KDEN 151800Z 18010KT 10SM FEW040 M05/M10 A3002"}]
        resp.raise_for_status = MagicMock()
        client.get = AsyncMock(return_value=resp)
        with patch("pm_bot.core.sources.metar._metar_cache", {}):
            result = await fetch_metar(client, "KDEN")
        assert result is not None
        assert result["temp_c"] == -5.0

    @pytest.mark.asyncio
    async def test_successful_with_temp(self):
        client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = [{"temp": 22.0, "observationTime": "2026-01-15T18:00:00Z"}]
        resp.raise_for_status = MagicMock()
        client.get = AsyncMock(return_value=resp)
        with patch("pm_bot.core.sources.metar._metar_cache", {}):
            result = await fetch_metar(client, "KLGA")
        assert result is not None
        assert result["icao"] == "KLGA"
        assert result["source"] == "metar"
        assert result["temp_c"] == 22.0

    @pytest.mark.asyncio
    async def test_non_dict_features(self):
        client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = ["not_a_dict"]
        resp.raise_for_status = MagicMock()
        client.get = AsyncMock(return_value=resp)
        with patch("pm_bot.core.sources.metar._metar_cache", {}):
            result = await fetch_metar(client, "KLGA")
        assert result is None

    @pytest.mark.asyncio
    async def test_dict_format_with_features_key(self):
        client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = {"features": [{"temp": 22.0}]}
        resp.raise_for_status = MagicMock()
        client.get = AsyncMock(return_value=resp)
        with patch("pm_bot.core.sources.metar._metar_cache", {}):
            result = await fetch_metar(client, "KLGA")
        assert result is not None
        assert result["temp_c"] == 22.0

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        from pm_bot.core.sources.metar import _metar_cache
        _metar_cache["metar:KLGA"] = {"icao": "KLGA", "temp_c": 25.0}
        client = AsyncMock()
        result = await fetch_metar(client, "KLGA")
        assert result is not None
        assert result["temp_c"] == 25.0
        client.get.assert_not_called()
        _metar_cache.pop("metar:KLGA", None)


class TestParseTempFromRaw:
    def test_positive_temp(self):
        result = _parse_temp_from_raw("KLGA 151800Z 18010KT 10SM FEW040 25/18 A3002")
        assert result == 25.0

    def test_negative_temp(self):
        result = _parse_temp_from_raw("KDEN 151800Z 18010KT 10SM FEW040 M05/M10 A3002")
        assert result == -5.0

    def test_no_match(self):
        result = _parse_temp_from_raw("no temp data")
        assert result is None


class TestGetIcaoForCity:
    def test_match(self):
        config = {"stations": {"KLGA": {"city": "New York"}}}
        result = get_icao_for_city(config, "New York")
        assert result == "KLGA"

    def test_case_insensitive(self):
        config = {"stations": {"KLGA": {"city": "new york"}}}
        result = get_icao_for_city(config, "New York")
        assert result == "KLGA"

    def test_no_match(self):
        config = {"stations": {"KLGA": {"city": "New York"}}}
        result = get_icao_for_city(config, "London")
        assert result is None

    def test_empty_config(self):
        result = get_icao_for_city({}, "New York")
        assert result is None
