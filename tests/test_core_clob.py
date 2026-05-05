from __future__ import annotations

from pm_bot.core.clob import compute_v2_taker_fee


class TestComputeV2TakerFee:
    def test_zero_price(self):
        fee = compute_v2_taker_fee(50, 0.0)
        assert fee == 0.0

    def test_extreme_price_near_0(self):
        fee = compute_v2_taker_fee(50, 0.01)
        assert 0 < fee < 0.01

    def test_midpoint_peak(self):
        fee = compute_v2_taker_fee(50, 0.5)
        expected = 50 / 10000.0 * 0.5 * 0.25
        assert abs(fee - expected) < 0.001

    def test_fee_decreases_at_tails(self):
        fee_mid = compute_v2_taker_fee(50, 0.5)
        fee_tail = compute_v2_taker_fee(50, 0.95)
        assert fee_tail < fee_mid

    def test_different_exponent(self):
        fee_05 = compute_v2_taker_fee(50, 0.5, exponent=0.5)
        fee_10 = compute_v2_taker_fee(50, 0.5, exponent=1.0)
        assert fee_10 != fee_05

    def test_different_rate_bps(self):
        fee_50 = compute_v2_taker_fee(50, 0.5)
        fee_100 = compute_v2_taker_fee(100, 0.5)
        assert fee_100 > fee_50

    def test_bps_50_with_exponent_05(self):
        fee = compute_v2_taker_fee(50, 0.5, exponent=0.5)
        expected = 50 / 10000.0 * 0.5 * (0.5 * 0.5) ** (0.5 - 1.0)
        assert abs(fee - expected) < 0.001

    def test_exponent_1_symmetry(self):
        fee_025 = compute_v2_taker_fee(50, 0.25, exponent=1.0)
        fee_075 = compute_v2_taker_fee(50, 0.75, exponent=1.0)
        assert abs(fee_025 - fee_075) < 0.001
