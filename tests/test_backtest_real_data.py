from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pm_bot.backtest.real_data import (
    RealDataFetcher,
    ResolvedEvent,
    ResolvedMarket,
    _extract_city,
    _extract_date_iso,
    _parse_flexible_date,
    _synthesize_ensemble,
    _is_weather_title,
    SERIES_SLUG_TO_CITY,
    WEATHER_SERIES_SLUGS,
    PricePoint,
)
from pm_bot.models.market import ForecastResult


class TestPricePoint:
    def test_creation(self):
        pp = PricePoint(timestamp=1700000000.0, price=0.55)
        assert pp.timestamp == 1700000000.0
        assert pp.price == 0.55


class TestResolvedMarket:
    def test_defaults(self):
        rm = ResolvedMarket(question="23°C", token_id="tok1", outcome="Yes", winning=True)
        assert rm.yes_price == 0.0
        assert rm.no_price == 0.0
        assert rm.price_history == []
        assert rm.price_source == ""

    def test_with_prices(self):
        rm = ResolvedMarket(question="23°C", token_id="tok1", outcome="Yes", winning=True,
                            yes_price=0.8, no_price=0.2)
        assert rm.yes_price == 0.8
        assert rm.no_price == 0.2

    def test_with_price_source(self):
        rm = ResolvedMarket(question="23°C", token_id="tok1", outcome="Yes", winning=True,
                            yes_price=0.4, no_price=0.6, price_source="dune")
        assert rm.price_source == "dune"


class TestResolvedEvent:
    def test_defaults(self):
        re = ResolvedEvent(
            event_id="ev1", title="t", slug="s",
            city="NYC", target_date="2026-01-15",
        )
        assert re.markets == []


class TestSeriesSlugs:
    def test_all_slugs_have_city(self):
        for slug in WEATHER_SERIES_SLUGS:
            assert slug in SERIES_SLUG_TO_CITY

    def test_cities_match(self):
        assert SERIES_SLUG_TO_CITY["nyc-daily-weather"] == "New York"
        assert SERIES_SLUG_TO_CITY["london-daily-weather"] == "London"


class TestExtractCity:
    def test_standard(self):
        assert _extract_city("High temperature in New York on January 15") == "New York"

    def test_nyc(self):
        assert _extract_city("High temp in NYC") == "New York"

    def test_no_match(self):
        assert _extract_city("Random event") is None

    def test_la(self):
        assert _extract_city("High temp in LA") == "Los Angeles"

    def test_canonical_central_park(self):
        result = _extract_city("New York's Central Park temperature")
        assert result == "New York"


class TestExtractDateIso:
    def test_iso_in_title(self):
        result = _extract_date_iso("High temp 2026-01-15 NYC")
        assert result == "2026-01-15"

    def test_month_day(self):
        result = _extract_date_iso("High temp in NYC on January 15")
        assert isinstance(result, str)

    def test_no_date(self):
        result = _extract_date_iso("Random event")
        assert result == ""

    def test_full_date(self):
        result = _extract_date_iso("High temp January 15, 2026")
        assert result == "2026-01-15"


class TestParseFlexibleDateExtended:
    def test_iso(self):
        dt = _parse_flexible_date("2026-01-15")
        assert dt is not None
        assert dt.year == 2026

    def test_abbreviated_month(self):
        dt = _parse_flexible_date("Jan 15")
        assert dt is not None
        assert dt.month == 1
        assert dt.day == 15

    def test_from_title(self):
        dt = _parse_flexible_date("", "High temp January 15th, 2026")
        assert dt is not None
        assert dt.year == 2026

    def test_iso_in_title(self):
        dt = _parse_flexible_date("", "Temperature 2026-03-20")
        assert dt is not None
        assert dt.month == 3

    def test_ordinal_date(self):
        dt = _parse_flexible_date("", "January 15th 2026")
        assert dt is not None

    def test_empty_string(self):
        dt = _parse_flexible_date("")
        assert dt is None

    def test_empty_string_and_title(self):
        dt = _parse_flexible_date("", "no date here")
        assert dt is None


class TestRealDataFetcherFetchClobPriceAt:
    @pytest.mark.asyncio
    async def test_no_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            resp = MagicMock()
            resp.json.return_value = {"history": []}
            resp.raise_for_status = MagicMock()
            client.get = AsyncMock(return_value=resp)
            result = await fetcher.fetch_clob_price_at(client, "tok1", 1700000000.0)
            assert result is None
            fetcher.close()

    @pytest.mark.asyncio
    async def test_with_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            resp = MagicMock()
            resp.json.return_value = {
                "history": [{"t": 1700000000, "p": 0.55}, {"t": 1700000100, "p": 0.56}],
            }
            resp.raise_for_status = MagicMock()
            client.get = AsyncMock(return_value=resp)
            result = await fetcher.fetch_clob_price_at(client, "tok1", 1700000000.0)
            assert result is not None
            assert abs(result - 0.55) < 0.01
            fetcher.close()


class TestRealDataFetcherEnrichEventsWithClobPrices:
    @pytest.mark.asyncio
    async def test_short_token_id_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            market = ResolvedMarket(
                question="23°C", token_id="short", outcome="Yes", winning=True,
            )
            ev = ResolvedEvent(
                event_id="ev1", title="t", slug="s",
                city="New York", target_date="2026-01-15",
                markets=[market],
            )
            await fetcher.enrich_events_with_clob_prices(client, [ev])
            assert market.yes_price == 0.0
            fetcher.close()

    @pytest.mark.asyncio
    async def test_empty_token_id_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            market = ResolvedMarket(
                question="23°C", token_id="", outcome="Yes", winning=True,
            )
            ev = ResolvedEvent(
                event_id="ev1", title="t", slug="s",
                city="New York", target_date="2026-01-15",
                markets=[market],
            )
            await fetcher.enrich_events_with_clob_prices(client, [ev])
            fetcher.close()


class TestRealDataFetcherFetchResolvedWeatherEvents:
    @pytest.mark.asyncio
    async def test_no_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock, return_value=[]):
                result = await fetcher.fetch_resolved_weather_events(client, days=30)
            assert result == []
            fetcher.close()


class TestRealDataFetcherFetchActiveMarketPrices:
    @pytest.mark.asyncio
    async def test_no_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock, return_value=[]):
                result = await fetcher.fetch_active_market_prices(client, days=30)
            assert result == {}
            fetcher.close()

    @pytest.mark.asyncio
    async def test_with_active_markets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            event_data = [{
                "closed": False,
                "markets": [{
                    "question": "between 23-24°C",
                    "clobTokenIds": "[\"tok1\"]",
                    "outcomes": "[\"Yes\", \"No\"]",
                    "outcomePrices": "[\"0.55\", \"0.45\"]",
                }],
            }]
            empty = []
            side_effects = [event_data] + [empty] * (len(WEATHER_SERIES_SLUGS) - 1)
            with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock, side_effect=side_effects):
                result = await fetcher.fetch_active_market_prices(client, days=30)
            assert "tok1" in result
            assert result["tok1"] == 0.55
            fetcher.close()


class TestRealDataFetcherPrefetchForecasts:
    @pytest.mark.asyncio
    async def test_unknown_city(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            await fetcher.prefetch_forecasts(client, ["Atlantis"], 30)
            assert len(fetcher._forecast_cache) == 0
            fetcher.close()

    @pytest.mark.asyncio
    async def test_successful(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            resp = MagicMock()
            resp.json.return_value = {
                "daily": {
                    "time": ["2026-01-15"],
                    "temperature_2m_max": [25.0],
                }
            }
            resp.raise_for_status = MagicMock()
            client.get = AsyncMock(return_value=resp)
            await fetcher.prefetch_forecasts(client, ["New York"], 30)
            assert len(fetcher._forecast_cache) > 0
            fetcher.close()

    @pytest.mark.asyncio
    async def test_http_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            client.get = AsyncMock(side_effect=httpx.HTTPError("fail"))
            await fetcher.prefetch_forecasts(client, ["New York"], 30)
            assert len(fetcher._forecast_cache) == 0
            fetcher.close()


class TestRealDataFetcherFetchMarketPrices:
    @pytest.mark.asyncio
    async def test_cached(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            conn = fetcher._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO bt_price_history (token_id, ts, price, source) VALUES (?, ?, ?, 'clob')",
                ("tok1", 1700000000.0, 0.55),
            )
            conn.commit()
            client = AsyncMock()
            result = await fetcher.fetch_market_prices(
                client, ["tok1"], 1700000000.0, 1700001000.0,
            )
            assert "tok1" in result
            assert len(result["tok1"]) == 1
            fetcher.close()

    @pytest.mark.asyncio
    async def test_no_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            resp = MagicMock()
            resp.json.return_value = None
            resp.raise_for_status = MagicMock()
            client.get = AsyncMock(return_value=resp)
            result = await fetcher.fetch_market_prices(
                client, ["tok_x"], 1700000000.0, 1700001000.0,
            )
            assert result == {}
            fetcher.close()

    @pytest.mark.asyncio
    async def test_with_history_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            resp = MagicMock()
            resp.json.return_value = {
                "history": [{"t": 1700000000, "p": 0.55}, {"t": 1700000100, "p": 0.56}],
            }
            resp.raise_for_status = MagicMock()
            client.get = AsyncMock(return_value=resp)
            result = await fetcher.fetch_market_prices(
                client, ["tok_new"], 1700000000.0, 1700001000.0,
            )
            assert "tok_new" in result
            assert len(result["tok_new"]) == 2
            fetcher.close()


class TestRealDataFetcherRateLimiter:
    @pytest.mark.asyncio
    async def test_get_with_retry_429(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            resp_429 = MagicMock()
            resp_429.status_code = 429
            resp_ok = MagicMock()
            resp_ok.status_code = 200
            resp_ok.json.return_value = {"data": "ok"}
            resp_ok.raise_for_status = MagicMock()
            client.get = AsyncMock(side_effect=[resp_429, resp_ok])
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await fetcher._get_with_retry(client, "http://test.com")
            assert result is not None
            fetcher.close()

    @pytest.mark.asyncio
    async def test_get_with_retry_persistent_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            client.get = AsyncMock(side_effect=httpx.HTTPError("fail"))
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await fetcher._get_with_retry(client, "http://test.com")
            assert result is None
            fetcher.close()


class TestRealDataFetcherParseResolvedMarket:
    def test_valid_market(self):
        fetcher = RealDataFetcher(db_path=Path(tempfile.mkdtemp()) / "test.db")
        m = {
            "question": "between 23-24°C",
            "id": "m1",
            "clobTokenIds": "[\"tok1\", \"tok2\"]",
            "outcomes": "[\"Yes\", \"No\"]",
            "outcomePrices": "[\"0.95\", \"0.05\"]",
        }
        result = fetcher._parse_resolved_market(m)
        assert result is not None
        assert result.winning is True
        assert result.yes_price == 0.95
        assert result.token_id == "tok1"
        fetcher.close()

    def test_no_temp_question(self):
        fetcher = RealDataFetcher(db_path=Path(tempfile.mkdtemp()) / "test.db")
        m = {
            "question": "Will it rain?",
            "id": "m1",
            "clobTokenIds": "[\"tok1\"]",
            "outcomes": "[\"Yes\", \"No\"]",
            "outcomePrices": "[\"0.50\", \"0.50\"]",
        }
        result = fetcher._parse_resolved_market(m)
        assert result is None
        fetcher.close()

    def test_list_clob_token_ids(self):
        fetcher = RealDataFetcher(db_path=Path(tempfile.mkdtemp()) / "test.db")
        m = {
            "question": "23°C",
            "id": "m1",
            "clobTokenIds": ["tok1", "tok2"],
            "outcomes": "[\"Yes\", \"No\"]",
            "outcomePrices": "[\"0.50\", \"0.50\"]",
        }
        result = fetcher._parse_resolved_market(m)
        assert result is not None
        assert result.token_id == "tok1"
        fetcher.close()

    def test_no_token_ids(self):
        fetcher = RealDataFetcher(db_path=Path(tempfile.mkdtemp()) / "test.db")
        m = {
            "question": "23°C",
            "id": "m1",
            "clobTokenIds": "",
            "outcomes": "[\"Yes\", \"No\"]",
            "outcomePrices": "[\"0.50\", \"0.50\"]",
        }
        result = fetcher._parse_resolved_market(m)
        assert result is not None
        assert result.token_id == "m1"
        fetcher.close()

    def test_empty_id_no_tokens(self):
        fetcher = RealDataFetcher(db_path=Path(tempfile.mkdtemp()) / "test.db")
        m = {
            "question": "23°C",
            "id": "",
            "clobTokenIds": "",
            "outcomes": "[\"Yes\", \"No\"]",
            "outcomePrices": "[\"0.50\", \"0.50\"]",
        }
        result = fetcher._parse_resolved_market(m)
        assert result is None
        fetcher.close()

    def test_invalid_clob_token_ids_json(self):
        fetcher = RealDataFetcher(db_path=Path(tempfile.mkdtemp()) / "test.db")
        m = {
            "question": "23°C",
            "id": "m1",
            "clobTokenIds": "not valid json{{{",
            "outcomes": "[\"Yes\", \"No\"]",
            "outcomePrices": "[\"0.50\", \"0.50\"]",
        }
        result = fetcher._parse_resolved_market(m)
        assert result is not None
        assert result.token_id == "m1"
        fetcher.close()

    def test_fahrenheit_question(self):
        fetcher = RealDataFetcher(db_path=Path(tempfile.mkdtemp()) / "test.db")
        m = {
            "question": "between 75-76°F",
            "id": "m1",
            "clobTokenIds": "[\"tok1\"]",
            "outcomes": "[\"Yes\", \"No\"]",
            "outcomePrices": "[\"0.80\", \"0.20\"]",
        }
        result = fetcher._parse_resolved_market(m)
        assert result is not None
        assert result.yes_price == 0.80
        fetcher.close()

    def test_list_outcomes(self):
        fetcher = RealDataFetcher(db_path=Path(tempfile.mkdtemp()) / "test.db")
        m = {
            "question": "23°C",
            "id": "m1",
            "clobTokenIds": "[\"tok1\"]",
            "outcomes": ["Yes", "No"],
            "outcomePrices": [0.5, 0.5],
        }
        result = fetcher._parse_resolved_market(m)
        assert result is not None
        fetcher.close()

    def test_non_winning_market(self):
        fetcher = RealDataFetcher(db_path=Path(tempfile.mkdtemp()) / "test.db")
        m = {
            "question": "23°C",
            "id": "m1",
            "clobTokenIds": "[\"tok1\"]",
            "outcomes": "[\"Yes\", \"No\"]",
            "outcomePrices": "[\"0.05\", \"0.95\"]",
        }
        result = fetcher._parse_resolved_market(m)
        assert result is not None
        assert result.winning is False
        assert result.yes_price == 0.05
        fetcher.close()


class TestSynthesizeEnsemble:
    def test_deterministic(self):
        ens1 = _synthesize_ensemble(25.0, "New York")
        ens2 = _synthesize_ensemble(25.0, "New York")
        assert ens1 == ens2

    def test_correct_count(self):
        ens = _synthesize_ensemble(25.0, "New York")
        assert len(ens) == 51

    def test_centered(self):
        ens = _synthesize_ensemble(25.0, "New York")
        mean = sum(ens) / len(ens)
        assert abs(mean - 25.0) < 1.0


class TestIsWeatherTitle:
    def test_temperature(self):
        assert _is_weather_title("High temperature in NYC") is True

    def test_low_temp(self):
        assert _is_weather_title("Low temp in London") is True

    def test_non_weather(self):
        assert _is_weather_title("Election results") is False


class TestRealDataFetcherGetCachedForecast:
    def test_no_cache(self):
        fetcher = RealDataFetcher(db_path=Path(tempfile.mkdtemp()) / "test.db")
        result = fetcher.get_cached_forecast("New York", "2026-01-15")
        assert result is None
        fetcher.close()

    def test_in_memory_cache(self):
        fetcher = RealDataFetcher(db_path=Path(tempfile.mkdtemp()) / "test.db")
        fr = ForecastResult(
            city="New York", date="2026-01-15", model="gfs_seamless",
            temp_high_c=25.0, members=[25.0],
        )
        fetcher._forecast_cache["New York:2026-01-15:high"] = fr
        result = fetcher.get_cached_forecast("New York", "2026-01-15")
        assert result is not None
        assert result.temp_high_c == 25.0
        fetcher.close()

    def test_db_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = RealDataFetcher(db_path=db_path)
            conn = fetcher._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO bt_previous_forecasts (city, date, model, temp_high_c, members_json) VALUES (?, ?, ?, ?, ?)",
                ("New York", "2026-01-15", "gfs_seamless", 25.0, "[25.0, 26.0]"),
            )
            conn.commit()
            result = fetcher.get_cached_forecast("New York", "2026-01-15")
            assert result is not None
            assert result.temp_high_c == 25.0
            fetcher.close()


class TestRealDataFetcherGetCachedClobPrice:
    def test_no_cache(self):
        fetcher = RealDataFetcher(db_path=Path(tempfile.mkdtemp()) / "test.db")
        result = fetcher._get_cached_clob_price("tok1", 1700000000.0)
        assert result is None
        fetcher.close()

    def test_cached(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = RealDataFetcher(db_path=db_path)
            conn = fetcher._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO bt_price_history (token_id, ts, price, source) VALUES (?, ?, ?, 'clob')",
                ("tok1", 1700000000.0, 0.55),
            )
            conn.commit()
            result = fetcher._get_cached_clob_price("tok1", 1700000000.0)
            assert result == 0.55
            fetcher.close()


class TestRealDataFetcherGetActivePrice:
    def test_no_cache(self):
        fetcher = RealDataFetcher(db_path=Path(tempfile.mkdtemp()) / "test.db")
        result = fetcher.get_active_price("tok1")
        assert result is None
        fetcher.close()

    def test_cached(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = RealDataFetcher(db_path=db_path)
            conn = fetcher._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO bt_active_prices (token_id, yes_price, fetched_at) VALUES (?, ?, datetime('now'))",
                ("tok1", 0.55),
            )
            conn.commit()
            result = fetcher.get_active_price("tok1")
            assert result == 0.55
            fetcher.close()


class TestRealDataFetcherClose:
    def test_close_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            fetcher._get_conn()
            fetcher.close()
            fetcher.close()
            assert fetcher._conn is None


class TestRealDataFetcherDunePrices:
    @pytest.mark.asyncio
    async def test_no_api_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            result = await fetcher.fetch_dune_prices(client, "cond1", dune_api_key="")
            assert result == {}
            fetcher.close()

    @pytest.mark.asyncio
    async def test_with_api_key_no_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"result": {"rows": []}}
            resp.raise_for_status = MagicMock()
            client.get = AsyncMock(return_value=resp)
            result = await fetcher.fetch_dune_prices(
                client, "cond1", dune_api_key="test_key",
            )
            assert result == {}
            fetcher.close()

    @pytest.mark.asyncio
    async def test_with_api_key_and_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "result": {
                    "rows": [
                        {"token_id": "tok1", "price": 0.55, "hour": 1700000000.0},
                        {"token_id": "tok2", "price": 0.30, "hour": 1700000000.0},
                    ]
                }
            }
            resp.raise_for_status = MagicMock()
            client.get = AsyncMock(return_value=resp)
            result = await fetcher.fetch_dune_prices(
                client, "cond1", dune_api_key="test_key",
            )
            assert "tok1" in result
            assert result["tok1"] == 0.55
            assert "tok2" in result
            assert result["tok2"] == 0.30
            fetcher.close()


class TestRealDataFetcherEnrichEventsWithDunePrices:
    @pytest.mark.asyncio
    async def test_no_api_key_skips(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            market = ResolvedMarket(
                question="23°C", token_id="tok12345678901234567890",
                outcome="Yes", winning=True,
            )
            ev = ResolvedEvent(
                event_id="ev1", title="t", slug="s",
                city="New York", target_date="2026-01-15",
                markets=[market],
            )
            await fetcher.enrich_events_with_dune_prices(client, [ev], dune_api_key="")
            assert market.yes_price == 0.0  # unchanged
            fetcher.close()

    @pytest.mark.asyncio
    async def test_skips_clob_priced_markets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fetcher = RealDataFetcher(db_path=Path(tmpdir) / "test.db")
            client = AsyncMock()
            market = ResolvedMarket(
                question="23°C", token_id="tok12345678901234567890",
                outcome="Yes", winning=True,
                yes_price=0.55, no_price=0.45, price_source="clob",
            )
            ev = ResolvedEvent(
                event_id="ev1", title="t", slug="s",
                city="New York", target_date="2026-01-15",
                markets=[market],
            )
            # With Dune API key but market already has CLOB price
            with patch.object(fetcher, "fetch_dune_prices", new_callable=AsyncMock, return_value={"tok12345678901234567890": 0.40}):
                await fetcher.enrich_events_with_dune_prices(client, [ev], dune_api_key="test_key")
            # Should NOT override CLOB price
            assert market.yes_price == 0.55
            fetcher.close()


class TestRealDataFetcherCachedDunePrice:
    def test_no_cache(self):
        fetcher = RealDataFetcher(db_path=Path(tempfile.mkdtemp()) / "test.db")
        result = fetcher._get_cached_dune_price("tok1", 1700000000.0)
        assert result is None
        fetcher.close()

    def test_cached(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            fetcher = RealDataFetcher(db_path=db_path)
            conn = fetcher._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO bt_price_history (token_id, ts, price, source) VALUES (?, ?, ?, 'dune')",
                ("tok1", 1700000000.0, 0.55),
            )
            conn.commit()
            result = fetcher._get_cached_dune_price("tok1", 1700000000.0)
            assert result == 0.55
            fetcher.close()
