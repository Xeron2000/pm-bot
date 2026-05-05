from __future__ import annotations

from pm_bot.backtest.costs import CostModel, FillModel


class TestFillModel:
    def test_fill_probability_at_best(self):
        fm = FillModel()
        assert fm.fill_probability(0.50) == 0.50

    def test_fill_probability_tail(self):
        fm = FillModel()
        assert fm.fill_probability(0.10) == 0.10  # 0.01 <= 0.10 <= 0.15
        assert fm.fill_probability(0.90) == 0.10  # 0.85 <= 0.90 <= 0.99

    def test_fill_probability_very_low(self):
        fm = FillModel()
        assert fm.fill_probability(0.005) == 0.10  # <= 0.01

    def test_fill_probability_very_high(self):
        fm = FillModel()
        assert fm.fill_probability(0.995) == 0.10  # >= 0.99

    def test_fill_probability_inside(self):
        """Prices in the middle range use fill_prob_at_best."""
        fm = FillModel()
        assert fm.fill_probability(0.30) == 0.50
        assert fm.fill_probability(0.70) == 0.50

    def test_custom_fill_model(self):
        fm = FillModel(fill_prob_at_best=0.75, fill_prob_tail=0.20)
        assert fm.fill_probability(0.50) == 0.75
        assert fm.fill_probability(0.10) == 0.20

    def test_boundary_prices(self):
        fm = FillModel()
        assert fm.fill_probability(0.15) == 0.10  # exactly at tail_high
        assert fm.fill_probability(0.85) == 0.10  # exactly at tail_high2


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

    def test_fill_model_default(self):
        cm = CostModel()
        assert cm.fill_model is not None
        assert isinstance(cm.fill_model, FillModel)
        assert cm.fill_model.fill_prob_at_best == 0.50

    def test_forecast_penalty_default(self):
        cm = CostModel()
        assert cm.forecast_penalty_pct == 0.05

    def test_forecast_penalty_cost(self):
        cm = CostModel()
        penalty = cm.forecast_penalty_cost(price=0.50, amount_usd=100.0)
        expected = 0.50 * 100.0 * 0.05
        assert abs(penalty - expected) < 0.01

    def test_forecast_penalty_cost_zero(self):
        cm = CostModel()
        cm.forecast_penalty_pct = 0.0
        penalty = cm.forecast_penalty_cost(price=0.50, amount_usd=100.0)
        assert penalty == 0.0
