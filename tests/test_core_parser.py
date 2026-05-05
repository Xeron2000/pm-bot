from __future__ import annotations

from pm_bot.core.parser import parse_bucket
from pm_bot.models.market import TemperatureBucket


class TestParseBucketCelsius:
    def test_single_value_c(self):
        b = parse_bucket("23°C")
        assert b is not None
        assert b.temp_low == 23.0
        assert b.temp_high == 23.0
        assert b.temp_unit == "C"

    def test_range_c(self):
        b = parse_bucket("between 23-24°C")
        assert b is not None
        assert b.temp_low == 23.0
        assert b.temp_high == 24.0
        assert b.temp_unit == "C"

    def test_or_below_c(self):
        b = parse_bucket("16°C or below")
        assert b is not None
        assert b.temp_low == -999.0
        assert b.temp_high == 16.0
        assert b.is_low_tail is True

    def test_or_higher_c(self):
        b = parse_bucket("27°C or higher")
        assert b is not None
        assert b.temp_low == 27.0
        assert b.temp_high == 999.0
        assert b.is_high_tail is True

    def test_ge_and_lt_c(self):
        b = parse_bucket("≥ 25°C and < 26°C")
        assert b is not None
        assert b.temp_low == 25.0
        assert b.temp_high == 26.0

    def test_to_range_c(self):
        b = parse_bucket("25°C to 26°C")
        assert b is not None
        assert b.temp_low == 25.0
        assert b.temp_high == 26.0

    def test_dash_range_c(self):
        b = parse_bucket("23 - 24°C")
        assert b is not None
        assert b.temp_low == 23.0
        assert b.temp_high == 24.0


class TestParseBucketFahrenheit:
    def test_single_value_f(self):
        b = parse_bucket("90°F")
        assert b is not None
        assert b.temp_low == 90.0
        assert b.temp_high == 90.0
        assert b.temp_unit == "F"

    def test_range_f(self):
        b = parse_bucket("between 90-91°F")
        assert b is not None
        assert b.temp_low == 90.0
        assert b.temp_high == 91.0
        assert b.temp_unit == "F"

    def test_or_below_f(self):
        b = parse_bucket("54°F or below")
        assert b is not None
        assert b.temp_low == -999.0
        assert b.temp_high == 54.0
        assert b.is_low_tail is True

    def test_or_higher_f(self):
        b = parse_bucket("95°F or higher")
        assert b is not None
        assert b.temp_low == 95.0
        assert b.temp_high == 999.0
        assert b.is_high_tail is True

    def test_ge_and_lt_f(self):
        b = parse_bucket("≥ 90°F and < 95°F")
        assert b is not None
        assert b.temp_low == 90.0
        assert b.temp_high == 95.0

    def test_to_range_f(self):
        b = parse_bucket("90°F to 95°F")
        assert b is not None
        assert b.temp_low == 90.0
        assert b.temp_high == 95.0

    def test_dash_range_f(self):
        b = parse_bucket("54 - 55°F")
        assert b is not None
        assert b.temp_low == 54.0
        assert b.temp_high == 55.0


class TestParseBucketEdgeCases:
    def test_no_match(self):
        b = parse_bucket("Will it rain tomorrow?")
        assert b is None

    def test_preserves_metadata(self):
        b = parse_bucket("23°C", market_id="m1", yes_price=0.3, no_price=0.7, volume=100.0)
        assert b.market_id == "m1"
        assert b.yes_price == 0.3
        assert b.no_price == 0.7
        assert b.volume == 100.0

    def test_case_insensitive(self):
        b = parse_bucket("23°c")
        assert b is not None
        assert b.temp_unit == "C"

    def test_polymarket_format_with_prefix(self):
        b = parse_bucket("What will the high temperature be in NYC on Jan 15? (between 23-24°C)")
        assert b is not None
        assert b.temp_low == 23.0

    def test_tail_bound_constant(self):
        assert TemperatureBucket.TAIL_BOUND == 999.0
