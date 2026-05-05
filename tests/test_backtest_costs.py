from __future__ import annotations

from pm_bot.backtest.costs import CostModel


class TestCostModel:
    def test_taker_cost_structure(self):
        cm = CostModel()
        cost = cm.calculate_cost("taker", price=0.5, amount_usd=100.0)
        assert cost > 0
        wager = 0.5 * 100.0
        expected_fee = cm._taker_fee_rate(0.5) * wager
        expected_spread = wager * cm.default_spread_pct / 2.0
        expected_slippage = wager * cm.default_slippage_pct
        assert abs(cost - (expected_fee + expected_spread + expected_slippage)) < 0.01

    def test_maker_cost_only_spread(self):
        cm = CostModel()
        cost = cm.calculate_cost("maker", price=0.5, amount_usd=100.0)
        wager = 0.5 * 100.0
        expected_spread = wager * cm.default_spread_pct / 2.0
        assert abs(cost - expected_spread) < 0.01

    def test_taker_fee_rate_capped(self):
        cm = CostModel()
        rate = cm._taker_fee_rate(0.5)
        assert rate <= 0.0125

    def test_net_edge(self):
        cm = CostModel()
        net = cm.net_edge(gross_edge=0.05, side="taker", price=0.5, amount_usd=100.0)
        assert net < 0.05 * 100.0
        assert net > 0

    def test_stop_loss_slippage(self):
        cm = CostModel()
        slippage = cm.stop_loss_slippage(wager=100.0)
        assert abs(slippage - 3.0) < 0.01

    def test_fee_rate_bps_default(self):
        cm = CostModel()
        assert cm.taker_fee_rate_bps == 50

    def test_exponent_default(self):
        cm = CostModel()
        assert cm.taker_fee_exponent == 0.5

    def test_spread_default(self):
        cm = CostModel()
        assert cm.default_spread_pct == 0.02

    def test_slippage_default(self):
        cm = CostModel()
        assert cm.default_slippage_pct == 0.01
