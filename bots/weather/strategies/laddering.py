"""Laddering Strategy — Small Capital Optimized.

Inspired by neobrother's approach: dense orders across multiple buckets
in a predicted temperature range. Uses negative risk structure to enable
laddering with limited capital.

Key idea: Instead of betting on one bucket, spread bets across adjacent
buckets. If the actual temperature falls in the range, multiple buckets pay off.
The negative risk structure means you can buy YES on many buckets for less
than the total payout.
"""

from __future__ import annotations

import random
from typing import Sequence

from pm_bot.core.weather import bucket_probability_numpy
from pm_bot.models.market import ForecastResult, Recommendation, WeatherEvent
from pm_bot.strategies.base import Strategy


class LadderingStrategy(Strategy):
    """Dense laddering across temperature range buckets — small capital."""

    name = "laddering"

    def __init__(
        self,
        edge_threshold: float = 0.08,
        bankroll: float = 1000.0,
        kelly_fraction: float = 0.25,
        max_single_pct: float = 0.02,
        min_notional: float = 1.0,
        max_position_usd: float = 2.0,
        spread_degrees: float = 7.0,
        buckets_to_use: int = 6,
        min_price: float = 0.02,
        max_price: float = 0.15,
        max_ladder_cost: float = 0.90,
        *,
        rng: random.Random | None = None,
    ):
        super().__init__(
            edge_threshold=edge_threshold,
            bankroll=bankroll,
            kelly_fraction=kelly_fraction,
            max_single_pct=max_single_pct,
            min_notional=min_notional,
            max_position_usd=max_position_usd,
        )
        self.spread_degrees = spread_degrees
        self.buckets_to_use = buckets_to_use
        self.min_price = min_price
        self.max_price = max_price
        self.max_ladder_cost = max_ladder_cost
        self._rng = rng or random.Random()

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        """Generate laddering recommendations for a weather event."""
        if not event.buckets:
            return []

        forecast: ForecastResult | None = kwargs.get("forecast")
        bankroll = kwargs.get("bankroll", self.bankroll)

        price_weighted = sorted(event.buckets, key=lambda b: b.yes_price)
        if not price_weighted:
            return []

        center_bucket = min(price_weighted, key=lambda b: abs(b.temp_center_c - (forecast.mean if forecast else b.temp_center_c)))
        center_mid = center_bucket.temp_center_c

        half_spread = self.spread_degrees / 2
        range_low = center_mid - half_spread
        range_high = center_mid + half_spread

        candidates: list[tuple[object, float, float, float]] = []
        for b in event.buckets:
            bucket_mid = b.temp_center_c
            if not (range_low <= bucket_mid <= range_high):
                continue

            price = b.yes_price
            if not (self.min_price <= price <= self.max_price):
                continue

            model_prob = 0.0
            if forecast and forecast.members:
                model_prob = bucket_probability_numpy(forecast, b.temp_low_c, b.temp_high_c, b.temp_unit)
            edge = model_prob - price if forecast else 0.0
            if edge >= self.edge_threshold:
                candidates.append((b, edge, price, model_prob))

        if not candidates:
            return []

        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = candidates[: self.buckets_to_use]

        while len(candidates) > 1:
            total_cost = sum(c[2] for c in candidates)
            if total_cost <= self.max_ladder_cost:
                break
            candidates.pop()

        total_cost = sum(c[2] for c in candidates)
        if not candidates:
            return []

        recs: list[Recommendation] = []
        for b, edge, price, model_prob in candidates:
            win_payout = 1.0 - price
            loss_amt = price
            raw_kelly = (
                (model_prob * win_payout - (1 - model_prob) * loss_amt) / win_payout if model_prob > 0 else 0.0
            )
            if raw_kelly <= 0:
                continue

            kelly_per_bucket = raw_kelly * self.kelly_fraction
            position_usd = bankroll * kelly_per_bucket / len(candidates)
            position_usd = min(position_usd, self.max_position_usd)
            position_usd = max(position_usd, self.min_notional)

            recs.append(
                Recommendation(
                    strategy=self.name,
                    event=event,
                    bucket=b,
                    direction="YES",
                    edge=edge,
                    reasoning=(
                        f"Ladder {b.temp_low_c}-{b.temp_high_c}°C "
                        f"(edge={edge:.1%}, price={price:.1%}, model={model_prob:.1%}, LADDER COST={total_cost:.2f})"
                    ),
                    size_usd=position_usd,
                    kelly_fraction=raw_kelly,
                )
            )

        return recs
