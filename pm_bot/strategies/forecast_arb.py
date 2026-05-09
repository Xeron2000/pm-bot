"""
Forecast Arbitrage Strategy for $100 Aggressive Snowball.

Exploits massive mispricings when the model forecast diverges significantly
from market prices. Uses bucket_probability_numpy for model probability.
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Sequence

from pm_bot.models.market import WeatherEvent, TemperatureBucket, ForecastResult, Recommendation
from pm_bot.strategies.base import Strategy


class ForecastArbStrategy(Strategy):
    """
    Forecast arbitrage: exploit large model vs market mispricings.

    Looks for buckets where model probability differs from market price
    by more than a threshold. Buys YES when model >> market.
    """

    name = "forecast_arb"

    def __init__(
        self,
        edge_threshold: float = 0.15,
        bankroll: float = 100.0,
        kelly_fraction: float = 0.80,
        max_single_pct: float = 0.60,
        min_notional: float = 0.50,
        min_mispricing: float = 0.15,
        max_market_price: float = 0.30,
        **kwargs,
    ):
        super().__init__(
            edge_threshold=edge_threshold,
            bankroll=bankroll,
            kelly_fraction=kelly_fraction,
            max_single_pct=max_single_pct,
            min_notional=min_notional,
            **kwargs,
        )
        self.min_mispricing = min_mispricing
        self.max_market_price = max_market_price

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        if not event.buckets:
            return []

        forecast: ForecastResult | None = kwargs.get("forecast")
        if not forecast or not forecast.members:
            return []

        from pm_bot.core.weather import bucket_probability_numpy

        recs = []
        for b in event.buckets:
            model_prob = bucket_probability_numpy(forecast, b.temp_low_c, b.temp_high_c, b.temp_unit)
            if model_prob <= 0:
                continue

            market_price = b.yes_price
            if market_price <= 0:
                continue

            mispricing = model_prob - market_price

            # BUY YES when model >> market (underpriced)
            if mispricing >= self.min_mispricing and market_price <= self.max_market_price:
                rec = self._build_yes_rec(event, b, model_prob, market_price, mispricing)
                if rec:
                    recs.append(rec)

        recs.sort(key=lambda r: r.edge, reverse=True)
        return recs[:3]

    def _build_yes_rec(self, event, b, model_prob, market_price, mispricing):
        win_payout = 1.0 - market_price
        loss_amt = market_price
        raw_kelly = (model_prob * win_payout - (1 - model_prob) * loss_amt) / win_payout

        if raw_kelly <= 0:
            return None

        capped_kelly = min(raw_kelly * self.kelly_fraction, self.max_single_pct)
        position_size = max(self.bankroll * capped_kelly, self.min_notional)
        position_size = min(position_size, self.bankroll)

        return Recommendation(
            strategy=self.name,
            event=event,
            bucket=b,
            direction="YES",
            edge=mispricing,
            reasoning=f"ARB YES {b.temp_low_c}-{b.temp_high_c}C (model={model_prob:.1%} vs market={market_price:.1%})",
            size_usd=position_size,
            kelly_fraction=raw_kelly,
        )
