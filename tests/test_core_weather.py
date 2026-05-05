from __future__ import annotations

import math

import numpy as np

from pm_bot.core.weather import bucket_probability_numpy
from pm_bot.models.market import ForecastResult


class TestBucketProbabilityNumpyCelsius:
    def test_single_bucket_hit_with_members(self, forecast):
        prob = bucket_probability_numpy(forecast, 23.0, 23.0, "C")
        assert 0 < prob < 1

    def test_bucket_miss_with_members(self, forecast):
        prob = bucket_probability_numpy(forecast, 5.0, 5.0, "C")
        assert prob == 0.0

    def test_tail_high_with_members(self, forecast):
        prob = bucket_probability_numpy(forecast, 20.0, 999.0, "C")
        assert prob > 0

    def test_tail_low_with_members(self, forecast):
        prob = bucket_probability_numpy(forecast, -999.0, 20.0, "C")
        expected = float(np.sum(np.floor(np.array(forecast.members)) <= 20.0)) / len(forecast.members)
        assert abs(prob - expected) < 0.001

    def test_floor_semantics_23_4(self):
        f = ForecastResult(
            city="NYC", date="2026-01-15", model="gfs",
            temp_high_c=23.4, measure_type="high",
            members=[23.4],
        )
        prob_23 = bucket_probability_numpy(f, 23.0, 23.0, "C")
        prob_24 = bucket_probability_numpy(f, 24.0, 24.0, "C")
        assert prob_23 == 1.0
        assert prob_24 == 0.0

    def test_floor_semantics_24_0(self):
        f = ForecastResult(
            city="NYC", date="2026-01-15", model="gfs",
            temp_high_c=24.0, measure_type="high",
            members=[24.0],
        )
        prob_23 = bucket_probability_numpy(f, 23.0, 23.0, "C")
        prob_24 = bucket_probability_numpy(f, 24.0, 24.0, "C")
        assert prob_23 == 0.0
        assert prob_24 == 1.0

    def test_members_match_numpy_floor(self, forecast):
        arr = np.array(forecast.members)
        for temp in range(20, 28):
            prob = bucket_probability_numpy(forecast, float(temp), float(temp), "C")
            expected = float(np.sum(np.floor(arr) == temp)) / len(forecast.members)
            assert abs(prob - expected) < 0.001


class TestBucketProbabilityNumpyFahrenheit:
    def test_f_bucket_with_members(self):
        f = ForecastResult(
            city="Miami", date="2026-06-15", model="gfs",
            temp_high_c=33.0, measure_type="high",
            members=[33.0, 33.5, 34.0],
        )
        arr_f = np.array([33.0, 33.5, 34.0]) * 1.8 + 32.0
        floor_f = np.floor(arr_f)
        for temp_f in range(int(floor_f.min()), int(floor_f.max()) + 2):
            low_c = (temp_f - 32.0) / 1.8
            high_c = ((temp_f + 1) - 32.0) / 1.8
            prob = bucket_probability_numpy(f, low_c, high_c, "F")
            expected = float(np.sum((floor_f >= temp_f) & (floor_f <= temp_f + 1))) / len(f.members)
            assert abs(prob - expected) < 0.001

    def test_f_truncation_in_f_space(self):
        f = ForecastResult(
            city="Miami", date="2026-06-15", model="gfs",
            temp_high_c=33.33, measure_type="high",
            members=[33.33],
        )
        temp_f = 33.33 * 1.8 + 32.0
        floor_f = math.floor(temp_f)
        bucket_low_c = (floor_f - 32.0) / 1.8
        bucket_high_c = ((floor_f + 1) - 32.0) / 1.8
        prob = bucket_probability_numpy(f, bucket_low_c, bucket_high_c, "F")
        assert prob == 1.0

    def test_f_cross_bucket_boundary(self):
        f = ForecastResult(
            city="Miami", date="2026-06-15", model="gfs",
            temp_high_c=33.33, measure_type="high",
            members=[33.33],
        )
        temp_f = 33.33 * 1.8 + 32.0
        floor_f = math.floor(temp_f)
        next_bucket_c = (floor_f + 2 - 32.0) / 1.8
        next_high_c = (floor_f + 3 - 32.0) / 1.8
        prob = bucket_probability_numpy(f, next_bucket_c, next_high_c, "F")
        assert prob == 0.0

    def test_f_tail_high(self):
        f = ForecastResult(
            city="Miami", date="2026-06-15", model="gfs",
            temp_high_c=33.0, measure_type="high",
            members=[33.0, 34.0, 35.0],
        )
        prob = bucket_probability_numpy(f, 32.0, 999.0, "F")
        assert prob == 1.0

    def test_f_tail_low(self):
        f = ForecastResult(
            city="Miami", date="2026-06-15", model="gfs",
            temp_high_c=33.0, measure_type="high",
            members=[33.0, 34.0],
        )
        prob = bucket_probability_numpy(f, -999.0, 15.0, "F")
        assert prob == 0.0


class TestBucketProbabilityNoMembers:
    def test_continuous_approximation(self):
        f = ForecastResult(
            city="NYC", date="2026-01-15", model="gfs",
            temp_high_c=25.0, measure_type="high",
            members=[],
        )
        prob = bucket_probability_numpy(f, 25.0, 25.0, "C")
        assert prob > 0
        assert prob < 1

    def test_continuous_tail_high(self):
        f = ForecastResult(
            city="NYC", date="2026-01-15", model="gfs",
            temp_high_c=25.0, measure_type="high",
            members=[],
        )
        prob = bucket_probability_numpy(f, 20.0, 999.0, "C")
        assert prob > 0.5

    def test_continuous_tail_low(self):
        f = ForecastResult(
            city="NYC", date="2026-01-15", model="gfs",
            temp_high_c=25.0, measure_type="high",
            members=[],
        )
        prob = bucket_probability_numpy(f, -999.0, 30.0, "C")
        assert prob > 0.5

    def test_prob_bounded_0_1(self):
        f = ForecastResult(
            city="NYC", date="2026-01-15", model="gfs",
            temp_high_c=25.0, measure_type="high",
            members=[],
        )
        for low in [20.0, 25.0, 30.0]:
            prob = bucket_probability_numpy(f, low, low, "C")
            assert 0.0 <= prob <= 1.0

    def test_f_continuous_approximation(self):
        f = ForecastResult(
            city="Miami", date="2026-06-15", model="gfs",
            temp_high_c=33.0, measure_type="high",
            members=[],
        )
        prob = bucket_probability_numpy(f, 90.0, 92.0, "F")
        assert 0.0 <= prob <= 1.0
