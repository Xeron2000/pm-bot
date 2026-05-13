"""Forecast Arbitrage Strategy — Small Capital Optimized.

Exploits mispricings when the model forecast diverges significantly
from market prices. Uses bucket_probability_numpy for model probability.

This is the MOST promising strategy for small capital:
- Model-based edge is independent of market structure
- ECMWF/GFS forecasts are free and high quality
- 85-90% accuracy at 24-48h out
- Market often prices tails at 15-40% when true prob is 45%+

Small-capital rules (research-backed):
- 15% minimum mispricing (high-conviction only)
- Max market price $0.30 (avoid overpaying)
- $1-$2 per position, quarter Kelly
- Max 3 recommendations per event (focus on best opportunities)
- Use ensemble probability for robustness

Source: PolymarketWeather strategy guide — "the most durable edge"
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Sequence

from pm_bot.models.market import WeatherEvent, TemperatureBucket, ForecastResult, Recommendation
from pm_bot.strategies.base import Strategy


class ForecastArbStrategy(Strategy):
    """Forecast arbitrage: exploit large model vs market mispricings — small capital.

    Looks for buckets where model probability differs from market price
    by more than 15%. Buys YES when model >> market.

    Small-capital optimized:
    - 15% minimum mispricing (high-conviction only)
    - Max market price $0.30 (avoid overpaying)
    - $1-$2 per position, quarter Kelly
    - Max 3 recommendations per event
    """

    name = "forecast_arb"

    def __init__(
        self,
        edge_threshold: float = 0.15,
        bankroll: float = 1000.0,
        kelly_fraction: float = 0.25,
        max_single_pct: float = 0.02,
        min_notional: float = 1.0,
        max_position_usd: float = 2.0,
        min_mispricing: float = 0.15,
        max_market_price: float = 0.30,
        min_model_prob: float = 0.05,
        **kwargs,
    ):
        super().__init__(
            edge_threshold=edge_threshold,
            bankroll=bankroll,
            kelly_fraction=kelly_fraction,
            max_single_pct=max_single_pct,
            min_notional=min_notional,
            max_position_usd=max_position_usd,
            **kwargs,
        )
        self.min_mispricing = min_mispricing
        self.max_market_price = max_market_price
        self.min_model_prob = min_model_prob

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        if not event.buckets:
            return []

        forecast: ForecastResult | None = kwargs.get("forecast")
        bankroll = kwargs.get("bankroll", self.bankroll)

        if not forecast or not forecast.members:
            return []

        from pm_bot.core.weather import bucket_probability_numpy

        recs = []
        for b in event.buckets:
            model_prob = bucket_probability_numpy(forecast, b.temp_low_c, b.temp_high_c, b.temp_unit)
            if model_prob < self.min_model_prob:
                continue

            market_price = b.yes_price
            if market_price <= 0:
                continue

            mispricing = model_prob - market_price

            # BUY YES when model >> market (underpriced)
            if mispricing >= self.min_mispricing and market_price <= self.max_market_price:
                rec = self._build_yes_rec(event, b, model_prob, market_price, mispricing, bankroll)
                if rec:
                    recs.append(rec)

        recs.sort(key=lambda r: r.edge, reverse=True)
        return recs[:3]  # Max 3 recommendations per event

    def _build_yes_rec(self, event, b, model_prob, market_price, mispricing, bankroll):
        win_payout = 1.0 - market_price
        loss_amt = market_price
        raw_kelly = (model_prob * win_payout - (1 - model_prob) * loss_amt) / win_payout

        if raw_kelly <= 0:
            return None

        # Quarter Kelly, capped at $2 per position
        kelly_per_trade = raw_kelly * self.kelly_fraction
        position_usd = bankroll * kelly_per_trade
        position_usd = min(position_usd, self.max_position_usd)
        position_usd = max(position_usd, self.min_notional)

        return Recommendation(
            strategy=self.name,
            event=event,
            bucket=b,
            direction="YES",
            edge=mispricing,
            reasoning=f"ARB YES {b.temp_low_c}-{b.temp_high_c}C (model={model_prob:.1%} vs market={market_price:.1%}, mispricing={mispricing:.1%})",
            size_usd=position_usd,
            kelly_fraction=raw_kelly,
        )
