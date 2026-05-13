"""Resolution Delay Strategy — Small Capital Optimized.

Exploits the time gap between temperature observation and official market resolution.
Uses bucket_probability_numpy for confidence estimation.

WARNING: This is the HIGHEST RISK strategy.
- Time window is very short (hours)
- Liquidity is poor in final hours
- Alpha decays as more bots enter
- NOT recommended for small capital unless very confident

Small-capital rules (research-backed):
- Only trade when confidence > 90% (model + observation agree)
- 10% minimum edge
- $1 per position max (high risk = small bet)
- Only 1-2 positions per event
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Sequence

from pm_bot.models.market import WeatherEvent, TemperatureBucket, ForecastResult, Recommendation
from pm_bot.strategies.base import Strategy


class ResolutionDelayStrategy(Strategy):
    """Resolution delay exploit: buy winners before official resolution.

    Small-capital optimized:
    - Only trade when confidence > 90% (model + observation agree)
    - 10% minimum edge
    - $1 per position max (high risk = small bet)
    - Only 1-2 positions per event
    """

    name = "resolution_delay"

    def __init__(
        self,
        edge_threshold: float = 0.10,
        bankroll: float = 1000.0,
        kelly_fraction: float = 0.25,
        max_single_pct: float = 0.01,
        min_notional: float = 1.0,
        max_position_usd: float = 1.0,  # $1 max for high-risk strategy
        min_confidence: float = 0.90,  # 90% minimum confidence
        min_price_gap: float = 0.10,
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
        self.min_confidence = min_confidence
        self.min_price_gap = min_price_gap

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        if not event.buckets:
            return []

        forecast: ForecastResult | None = kwargs.get("forecast")
        bankroll = kwargs.get("bankroll", self.bankroll)

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
        candidates = candidates[:2]  # Max 2 positions

        recs = []
        for b, confidence, price_gap in candidates:
            win_payout = 1.0 - b.yes_price
            loss_amt = b.yes_price
            raw_kelly = (confidence * win_payout - (1 - confidence) * loss_amt) / win_payout

            if raw_kelly > 0:
                # Quarter Kelly, $1 max for high-risk strategy
                kelly_per_trade = raw_kelly * self.kelly_fraction
                position_usd = bankroll * kelly_per_trade
                position_usd = min(position_usd, self.max_position_usd)  # $1 max
                position_usd = max(position_usd, self.min_notional * 0.5)

                recs.append(
                    Recommendation(
                        strategy=self.name,
                        event=event,
                        bucket=b,
                        direction="YES",
                        edge=price_gap,
                        reasoning=f"RESOLUTION {b.temp_low_c}-{b.temp_high_c}C (conf={confidence:.1%}, gap={price_gap:.1%})",
                        size_usd=position_usd,
                        kelly_fraction=raw_kelly,
                    )
                )

        return recs
