from __future__ import annotations


class CostModel:
    taker_fee_rate: float = 0.05
    maker_fee_rate: float = 0.00
    default_spread_pct: float = 0.02
    default_slippage_pct: float = 0.01

    def calculate_cost(self, side: str, price: float, amount_usd: float) -> float:
        spread_cost = price * amount_usd * self.default_spread_pct / 2.0
        if side == "taker":
            fee = price * amount_usd * self.taker_fee_rate
            slippage = price * amount_usd * self.default_slippage_pct
            return fee + spread_cost + slippage
        return spread_cost

    def net_edge(self, gross_edge: float, side: str, price: float, amount_usd: float) -> float:
        cost = self.calculate_cost(side, price, amount_usd)
        return gross_edge * amount_usd - cost
