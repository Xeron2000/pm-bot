"""
Laddering Strategy for $100 Aggressive Snowball.

Inspired by neobrother's approach: dense orders across multiple buckets
in a predicted temperature range. Uses negative risk structure to enable
laddering with limited capital.

Key idea: Instead of betting on one bucket, spread bets across 5-8 adjacent
buckets. If the actual temperature falls in the range, multiple buckets pay off.
The negative risk structure means you can buy YES on many buckets for less
than the total payout.

Expected metrics (from research):
- 658-day sample: $6,320 profit
- High variance but strong expected value
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Sequence

from pm_bot.models.market import WeatherEvent, TemperatureBucket, ForecastResult, Recommendation
from pm_bot.strategies.base import Strategy


class LadderingStrategy(Strategy):
    """
    Dense laddering across temperature range buckets.

    Instead of one big bet, spread across multiple adjacent buckets.
    Uses the "negative risk" structure of Polymarket temperature markets.

    Parameters:
        spread_degrees: Temperature range to spread bets across (default 12°F / ~7°C)
        buckets_to_use: Number of buckets to buy in the spread (default 6)
        min_price: Minimum bucket price to buy (default $0.03)
        max_price: Maximum bucket price to buy (default $0.25)
        edge_threshold: Minimum edge required (default 0.03)
    """

    name = "laddering"

    def __init__(
        self,
        edge_threshold: float = 0.03,
        bankroll: float = 100.0,
        kelly_fraction: float = 0.60,
        max_single_pct: float = 0.50,
        min_notional: float = 0.50,
        spread_degrees: float = 7.0,  # ~12°F in Celsius
        buckets_to_use: int = 6,
        min_price: float = 0.03,
        max_price: float = 0.25,
        *,
        rng: random.Random | None = None,
    ):
        super().__init__(
            edge_threshold=edge_threshold,
            bankroll=bankroll,
            kelly_fraction=kelly_fraction,
            max_single_pct=max_single_pct,
            min_notional=min_notional,
        )
        self.spread_degrees = spread_degrees
        self.buckets_to_use = buckets_to_use
        self.min_price = min_price
        self.max_price = max_price
        self._rng = rng or random.Random()

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        """
        Generate laddering recommendations for a weather event.

        Spreads bets across multiple adjacent buckets in the forecast range.
        """
        if not event.buckets:
            return []

        # Find center of distribution (highest probability bucket)
        sorted_buckets = sorted(event.buckets, key=lambda b: b.yes_price, reverse=True)
        if not sorted_buckets:
            return []

        center_bucket = sorted_buckets[0]
        center_mid = center_bucket.temp_center_c

        # Calculate spread range
        half_spread = self.spread_degrees / 2
        range_low = center_mid - half_spread
        range_high = center_mid + half_spread

        # Find buckets in range
        candidates = []
        for b in event.buckets:
            bucket_mid = b.temp_center_c

            # Check if bucket is in our spread range
            if range_low <= bucket_mid <= range_high:
                # Filter by price range
                price = b.yes_price
                if self.min_price <= price <= self.max_price:
                    # Calculate edge (using yes_price as proxy for model prob)
                    # In real implementation, this would use forecast data
                    edge = price * 0.5  # Simplified edge estimate
                    if edge >= self.edge_threshold:
                        candidates.append((b, edge, price))

        if not candidates:
            return []

        # Sort by edge and take top N
        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = candidates[:self.buckets_to_use]

        recs = []
        for b, edge, price in candidates:
            # Kelly sizing for this bucket
            win_payout = 1.0 - price
            loss_amt = price
            raw_kelly = (price * win_payout - (1 - price) * loss_amt) / win_payout

            if raw_kelly <= 0:
                continue

            # Scale by number of buckets
            kelly_per_bucket = raw_kelly / len(candidates)
            capped_kelly = min(kelly_per_bucket * self.kelly_fraction, self.max_single_pct / len(candidates))
            position_size = max(self.bankroll * capped_kelly, self.min_notional / len(candidates))
            position_size = min(position_size, self.bankroll)

            recs.append(
                Recommendation(
                    strategy=self.name,
                    event=event,
                    bucket=b,
                    direction="YES",
                    edge=edge,
                    reasoning=f"Ladder bucket {b.temp_low_c}-{b.temp_high_c}°C (edge={edge:.1%}, price={price:.1%})",
                    size_usd=position_size,
                    kelly_fraction=kelly_per_bucket,
                )
            )

        return recs
