from __future__ import annotations

from pm_bot.backtest.real_data import _parse_flexible_date, _extract_city, _extract_date_iso


class TestParseFlexibleDate:
    def test_iso_format(self):
        dt = _parse_flexible_date("2026-01-15")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 1
        assert dt.day == 15

    def test_full_month_day(self):
        dt = _parse_flexible_date("January 15")
        assert dt is not None
        assert dt.month == 1
        assert dt.day == 15

    def test_none_on_invalid(self):
        dt = _parse_flexible_date("not a date")
        assert dt is None

    def test_october(self):
        dt = _parse_flexible_date("October 17")
        assert dt is not None
        assert dt.month == 10
        assert dt.day == 17


class TestExtractCity:
    def test_standard_title(self):
        city = _extract_city("High temperature in New York on January 15")
        assert city == "New York"

    def test_low_temp_title(self):
        city = _extract_city("Lowest temperature in London on Feb 22")
        assert city == "London"

    def test_no_match(self):
        city = _extract_city("Some random event")
        assert city is None


class TestExtractDateIso:
    def test_standard_title(self):
        date_str = _extract_date_iso("High temp in NYC on January 15")
        assert isinstance(date_str, str)

    def test_returns_string(self):
        date_str = _extract_date_iso("Temperature in London on October 17")
        assert isinstance(date_str, str)
