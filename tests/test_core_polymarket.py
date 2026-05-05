from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pm_bot.core.polymarket import (
    _parse_event,
    _parse_prices,
    _extract_city_date,
    _extract_airport,
    _is_weather_event,
    fetch_weather_events,
)


class TestIsWeatherEvent:
    def test_temperature_keyword(self):
        assert _is_weather_event({"title": "High temperature in NYC"}) is True

    def test_highest_temp_keyword(self):
        assert _is_weather_event({"title": "Highest temp in London"}) is True

    def test_high_temp_keyword(self):
        assert _is_weather_event({"title": "High temp in Miami"}) is True

    def test_non_weather(self):
        assert _is_weather_event({"title": "Who will win the election?"}) is False

    def test_empty_title(self):
        assert _is_weather_event({"title": ""}) is False


class TestExtractCityDate:
    def test_new_york(self):
        city, date = _extract_city_date("High temperature in New York on January 15")
        assert city == "New York"
        assert "January 15" in date

    def test_nyc_alias(self):
        city, date = _extract_city_date("High temp in NYC on January 15")
        assert city == "New York"

    def test_london(self):
        city, date = _extract_city_date("Temperature in London on October 17")
        assert city == "London"

    def test_no_city(self):
        city, date = _extract_city_date("Something random")
        assert city is None

    def test_date_with_year(self):
        city, date = _extract_city_date("High temp in NYC January 15, 2026")
        assert city == "New York"
        assert "2026" in date

    def test_la_alias(self):
        city, date = _extract_city_date("High temperature in LA on June 1")
        assert city == "Los Angeles"

    def test_central_park_alias(self):
        city, date = _extract_city_date("High temperature in New York's Central Park on June 1")
        assert city == "New York"

    def test_no_date(self):
        city, date = _extract_city_date("High temperature in New York")
        assert city == "New York"
        assert date == ""


class TestExtractAirport:
    def test_station_pattern(self):
        result = _extract_airport("LaGuardia Airport Station (KLGA)")
        assert result == "KLGA"

    def test_airport_pattern(self):
        result = _extract_airport("recorded at JFK Airport (KJFK)")
        assert result == "KJFK"

    def test_wunderground_url(self):
        result = _extract_airport("https://www.wunderground.com/history/daily/us/ny/KLGA")
        assert result == "KLGA"

    def test_recorded_at(self):
        result = _extract_airport("Temperature recorded at EGLL")
        assert result == "EGLL"

    def test_no_airport(self):
        result = _extract_airport("No airport code here")
        assert result is None


class TestParsePrices:
    def test_standard_format(self):
        yes, no = _parse_prices({
            "outcomes": "[\"Yes\", \"No\"]",
            "outcomePrices": "[\"0.60\", \"0.40\"]",
        })
        assert yes == 0.60
        assert no == 0.40

    def test_reversed(self):
        yes, no = _parse_prices({
            "outcomes": "[\"No\", \"Yes\"]",
            "outcomePrices": "[\"0.40\", \"0.60\"]",
        })
        assert yes == 0.60
        assert no == 0.40

    def test_invalid_prices(self):
        yes, no = _parse_prices({
            "outcomes": "[\"Yes\", \"No\"]",
            "outcomePrices": "[\"abc\", \"def\"]",
        })
        assert yes == 0.0
        assert no == 0.0

    def test_non_string(self):
        yes, no = _parse_prices({
            "outcomes": ["Yes", "No"],
            "outcomePrices": [0.6, 0.4],
        })
        assert yes == 0.0
        assert no == 0.0


class TestParseEvent:
    def test_weather_event_with_buckets(self):
        ev = {
            "id": "ev1",
            "title": "High temperature in New York on January 15",
            "slug": "nyc-jan-15",
            "description": "Station (KLGA)",
            "markets": [
                {
                    "question": "between 23-24°C",
                    "id": "m1",
                    "outcomes": "[\"Yes\", \"No\"]",
                    "outcomePrices": "[\"0.30\", \"0.70\"]",
                    "volume": 500.0,
                },
            ],
        }
        result = _parse_event(ev)
        assert result is not None
        assert result.city == "New York"
        assert len(result.buckets) == 1
        assert result.airport_code == "KLGA"

    def test_non_weather_event(self):
        ev = {
            "id": "ev2",
            "title": "Who will win the election?",
            "markets": [],
        }
        result = _parse_event(ev)
        assert result is None

    def test_no_city(self):
        ev = {
            "id": "ev3",
            "title": "Some event",
            "markets": [{"question": "23°C", "id": "m1"}],
        }
        result = _parse_event(ev)
        assert result is None

    def test_no_buckets(self):
        ev = {
            "id": "ev4",
            "title": "High temperature in New York on January 15",
            "markets": [
                {"question": "Will it rain?", "id": "m1"},
            ],
        }
        result = _parse_event(ev)
        assert result is None

    def test_detect_temp_from_market_question(self):
        ev = {
            "id": "ev5",
            "title": "Weather prediction for New York on January 15",
            "markets": [
                {"question": "between 23-24°C", "id": "m1",
                 "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.50\", \"0.50\"]"},
            ],
        }
        result = _parse_event(ev)
        assert result is not None

    def test_buckets_sorted(self):
        ev = {
            "id": "ev6",
            "title": "High temperature in New York on January 15",
            "markets": [
                {"question": "25°C", "id": "m1",
                 "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.30\", \"0.70\"]"},
                {"question": "23°C", "id": "m2",
                 "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.20\", \"0.80\"]"},
                {"question": "27°C or higher", "id": "m3",
                 "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.10\", \"0.90\"]"},
            ],
        }
        result = _parse_event(ev)
        assert result is not None
        temps = [b.temp_low for b in result.buckets]
        assert temps == sorted(temps)

    def test_non_dict_market(self):
        ev = {
            "id": "ev7",
            "title": "High temperature in New York on January 15",
            "markets": ["not a dict"],
        }
        result = _parse_event(ev)
        assert result is None


class TestFetchWeatherEvents:
    @pytest.mark.asyncio
    async def test_empty_response(self):
        client = AsyncMock()
        with patch("pm_bot.core.polymarket._get", new_callable=AsyncMock, return_value=[]):
            result = await fetch_weather_events(client)
        assert result == []

    @pytest.mark.asyncio
    async def test_http_error_breaks(self):
        import httpx
        client = AsyncMock()
        with patch("pm_bot.core.polymarket._get", new_callable=AsyncMock, side_effect=httpx.HTTPError("fail")):
            result = await fetch_weather_events(client)
        assert result == []

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        client = AsyncMock()
        events_data = [
            {
                "id": "ev1",
                "title": "High temperature in New York on January 15",
                "slug": "nyc-jan-15",
                "description": "",
                "markets": [
                    {"question": "23°C", "id": "m1",
                     "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.50\", \"0.50\"]"},
                ],
            },
        ]
        with patch("pm_bot.core.polymarket._get", new_callable=AsyncMock, return_value=events_data):
            result = await fetch_weather_events(client)
        assert len(result) == 1
        assert result[0].city == "New York"

    @pytest.mark.asyncio
    async def test_pagination(self):
        client = AsyncMock()
        first_page = [
            {"id": "ev1", "title": "High temperature in NYC on January 15",
             "slug": "nyc-1", "description": "",
             "markets": [{"question": "23°C", "id": "m1",
                          "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.50\", \"0.50\"]"}]},
        ] * 500
        second_page = []
        with patch("pm_bot.core.polymarket._get", new_callable=AsyncMock, side_effect=[first_page, second_page]):
            result = await fetch_weather_events(client)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_include_closed(self):
        client = AsyncMock()
        with patch("pm_bot.core.polymarket._get", new_callable=AsyncMock, return_value=[]):
            result = await fetch_weather_events(client, include_closed=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_duplicate_events(self):
        client = AsyncMock()
        event = {
            "id": "ev1",
            "title": "High temperature in New York on January 15",
            "slug": "nyc-jan-15",
            "description": "",
            "markets": [
                {"question": "23°C", "id": "m1",
                 "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.50\", \"0.50\"]"},
            ],
        }
        with patch("pm_bot.core.polymarket._get", new_callable=AsyncMock, return_value=[event, event]):
            result = await fetch_weather_events(client)
        assert len(result) == 1
