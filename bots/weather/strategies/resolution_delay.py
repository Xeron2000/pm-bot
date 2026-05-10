"""
Resolution Delay Strategy for $100 Aggressive Snowball.

Exploits the time gap between temperature observation and official market resolution.
Uses bucket_probability_numpy for confidence estimation.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Sequence

from pm_bot.models.market import WeatherEvent, TemperatureBucket, ForecastResult, Recommendation
from pm_bot.strategies.base import Strategy


class ResolutionDelayStrategy(Strategy):
    """
    Resolution delay exploit: buy winners before official resolution.
    """

    name = "resolution_delay"

    def __init__(
        self,
        edge_threshold: float = 0.10,
        bankroll: float = 100.0,
        kelly_fraction: float = 0.80,
        max_single_pct: float = 0.60,
        min_notional: float = 0.50,
        min_confidence: float = 0.80,
        min_price_gap: float = 0.10,
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
        self.min_confidence = min_confidence
        self.min_price_gap = min_price_gap

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        if not event.buckets:
            return []

        forecast: ForecastResult | None = kwargs.get("forecast")

        from pm_bot.core.weather import bucket_probability_numpy

        candidates = []
        for b in event.buckets:
            # Estimate confidence using forecast
            if forecast and forecast.members:
                confidence = bucket_probability_numpy(forecast, b.temp_low_c, b.temp_high_c, b.temp_unit)
            else:
                confidence = b.yes_price * 1.2

            if confidence < self.min_confidence:
                continue

            price_gap = 1.0 - b.yes_price
            if price_gap < self.min_price_gap:
                continue

            candidates.append((b, confidence, price_gap))

        if not candidates:
            return []

        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = candidates[:2]

        recs = []
        for b, confidence, price_gap in candidates:
            win_payout = 1.0 - b.yes_price
            loss_amt = b.yes_price
            raw_kelly = (confidence * win_payout - (1 - confidence) * loss_amt) / win_payout

            if raw_kelly > 0:
                capped_kelly = min(raw_kelly * self.kelly_fraction, self.max_single_pct)
                position_size = max(self.bankroll * capped_kelly, self.min_notional)
                position_size = min(position_size, self.bankroll)

                recs.append(Recommendation(
                    strategy=self.name,
                    event=event,
                    bucket=b,
                    direction="YES",
                    edge=price_gap,
                    reasoning=f"RESOLUTION {b.temp_low_c}-{b.temp_high_c}C (conf={confidence:.1%}, gap={price_gap:.1%})",
                    size_usd=position_size,
                    kelly_fraction=raw_kelly,
                ))

        return recs
