from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from pm_bot.backtest.data import HistoricalDataFetcher


class TestHistoricalDataFetcherInit:
    def test_creates_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sub" / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            conn = fetcher._get_conn()
            assert conn is not None
            fetcher.close()

    def test_close_clears_conn(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            fetcher._get_conn()
            fetcher.close()
            assert fetcher._conn is None


class TestHistoricalDataFetcherForecast:
    @pytest.mark.asyncio
    async def test_cached_forecast(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            conn = fetcher._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO backtest_forecasts (city, date, model, temp_high_c, members_json) VALUES (?, ?, ?, ?, ?)",
                ("New York", "2026-01-15", "gfs_seamless", 25.0, "[25.0, 26.0]"),
            )
            conn.commit()
            result = await fetcher.fetch_historical_forecasts(AsyncMock(), "New York", "2026-01-15")
            assert result is not None
            assert result.temp_high_c == 25.0
            fetcher.close()

    @pytest.mark.asyncio
    async def test_unknown_city(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            result = await fetcher.fetch_historical_forecasts(AsyncMock(), "Atlantis", "2026-01-15")
            assert result is None
            fetcher.close()

    @pytest.mark.asyncio
    async def test_api_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            client = AsyncMock()
            client.get = AsyncMock(side_effect=httpx.HTTPError("fail"))
            result = await fetcher.fetch_historical_forecasts(client, "New York", "2026-01-15")
            assert result is None
            fetcher.close()

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            client = AsyncMock()
            resp = MagicMock()
            resp.json.return_value = {
                "daily": {
                    "temperature_2m_max": [25.0],
                    "temperature_2m_max_member01": [24.0],
                    "temperature_2m_max_member02": [26.0],
                }
            }
            resp.raise_for_status = MagicMock()
            client.get = AsyncMock(return_value=resp)
            result = await fetcher.fetch_historical_forecasts(client, "New York", "2026-01-15")
            assert result is not None
            assert result.temp_high_c == 25.0
            fetcher.close()

    @pytest.mark.asyncio
    async def test_no_temp_in_response(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            client = AsyncMock()
            resp = MagicMock()
            resp.json.return_value = {"daily": {"temperature_2m_max": []}}
            resp.raise_for_status = MagicMock()
            client.get = AsyncMock(return_value=resp)
            result = await fetcher.fetch_historical_forecasts(client, "New York", "2026-01-15")
            assert result is None
            fetcher.close()

    @pytest.mark.asyncio
    async def test_string_temp_in_response(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            client = AsyncMock()
            resp = MagicMock()
            resp.json.return_value = {"daily": {"temperature_2m_max": ["not a number"]}}
            resp.raise_for_status = MagicMock()
            client.get = AsyncMock(return_value=resp)
            result = await fetcher.fetch_historical_forecasts(client, "New York", "2026-01-15")
            assert result is None
            fetcher.close()


class TestHistoricalDataFetcherObservations:
    @pytest.mark.asyncio
    async def test_cached_observation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            conn = fetcher._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO backtest_observations (city, date, temp_high_c) VALUES (?, ?, ?)",
                ("New York", "2026-01-15", 25.0),
            )
            conn.commit()
            result = await fetcher.fetch_historical_observations(AsyncMock(), "New York", "2026-01-15")
            assert result == 25.0
            fetcher.close()

    @pytest.mark.asyncio
    async def test_unknown_city(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            result = await fetcher.fetch_historical_observations(AsyncMock(), "Atlantis", "2026-01-15")
            assert result is None
            fetcher.close()

    @pytest.mark.asyncio
    async def test_api_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            client = AsyncMock()
            client.get = AsyncMock(side_effect=httpx.HTTPError("fail"))
            result = await fetcher.fetch_historical_observations(client, "New York", "2026-01-15")
            assert result is None
            fetcher.close()

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            client = AsyncMock()
            resp = MagicMock()
            resp.json.return_value = {
                "daily": {"temperature_2m_max": [25.5]}
            }
            resp.raise_for_status = MagicMock()
            client.get = AsyncMock(return_value=resp)
            result = await fetcher.fetch_historical_observations(client, "New York", "2026-01-15")
            assert result == 25.5
            fetcher.close()

    @pytest.mark.asyncio
    async def test_no_temp_in_response(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            client = AsyncMock()
            resp = MagicMock()
            resp.json.return_value = {"daily": {"temperature_2m_max": []}}
            resp.raise_for_status = MagicMock()
            client.get = AsyncMock(return_value=resp)
            result = await fetcher.fetch_historical_observations(client, "New York", "2026-01-15")
            assert result is None
            fetcher.close()


class TestHistoricalDataFetcherMarketPrices:
    @pytest.mark.asyncio
    async def test_cached_prices(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            conn = fetcher._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO backtest_prices (event_id, bucket_key, yes_price, no_price) VALUES (?, ?, ?, ?)",
                ("ev1", "25-26", 0.6, 0.4),
            )
            conn.commit()
            result = await fetcher.fetch_historical_market_prices(AsyncMock(), "ev1")
            assert "25-26" in result
            assert result["25-26"]["yes"] == 0.6
            fetcher.close()

    @pytest.mark.asyncio
    async def test_no_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            client = AsyncMock()
            resp = MagicMock()
            resp.json.return_value = {"history": []}
            resp.raise_for_status = MagicMock()
            client.get = AsyncMock(return_value=resp)
            result = await fetcher.fetch_historical_market_prices(client, "no_ev")
            assert result == {}
            fetcher.close()

    @pytest.mark.asyncio
    async def test_api_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            client = AsyncMock()
            client.get = AsyncMock(side_effect=httpx.HTTPError("fail"))
            result = await fetcher.fetch_historical_market_prices(client, "no_ev")
            assert result == {}
            fetcher.close()

    @pytest.mark.asyncio
    async def test_successful_fetch_with_prices(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            client = AsyncMock()
            resp = MagicMock()
            resp.json.return_value = {
                "history": [{"yes_price": 0.6, "price_1": 0.3, "no_price": 0.4}],
            }
            resp.raise_for_status = MagicMock()
            client.get = AsyncMock(return_value=resp)
            result = await fetcher.fetch_historical_market_prices(client, "ev2")
            assert len(result) > 0
            fetcher.close()


class TestHistoricalDataFetcherClose:
    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = HistoricalDataFetcher(db_path=db_path)
            fetcher._get_conn()
            fetcher.close()
            fetcher.close()
            assert fetcher._conn is None
