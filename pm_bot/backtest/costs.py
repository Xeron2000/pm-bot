from __future__ import annotations

from pm_bot.core.clob import compute_v2_taker_fee


class CostModel:
    taker_fee_rate_bps: int = 100
    maker_fee_rate: float = 0.00
    default_spread_pct: float = 0.02
    default_slippage_pct: float = 0.01

    def _taker_fee_rate(self, price: float) -> float:
        return min(compute_v2_taker_fee(self.taker_fee_rate_bps, price), 0.0125)

    def calculate_cost(self, side: str, price: float, amount_usd: float) -> float:
        spread_cost = price * amount_usd * self.default_spread_pct / 2.0
        if side == "taker":
            fee = self._taker_fee_rate(price) * amount_usd
            slippage = price * amount_usd * self.default_slippage_pct
            return fee + spread_cost + slippage
        return spread_cost

    def net_edge(self, gross_edge: float, side: str, price: float, amount_usd: float) -> float:
        cost = self.calculate_cost(side, price, amount_usd)
        return gross_edge * amount_usd - cost
