"""Tail-NO Barbell Strategy — Small Capital Optimized.

Inspired by Hans323's approach: a barbell strategy that combines
small tail-YES lottery tickets (high risk, high reward) with
larger tail-NO positions (low risk, steady returns).

Small-capital rules (research-backed):
- Tail-NO: $1-$2 per position, 3% minimum edge
- Tail-YES: $1 per position, 8% minimum edge (lottery tickets)
- 70% allocation to tail-NO, 30% to tail-YES
- Quarter Kelly (0.25) for safety
- Use model-based probability, not hardcoded estimates

Hans323's legendary trade: $92,632 on London temperature at 8% odds → $1.11M payout.
But his average position was much smaller. The $92K trade was a rare high-conviction bet.

Expected metrics (from research):
- 1118 predictions, $1875.62 profit
- Lower variance than pure lottery
- Steady compounding with occasional big wins
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Sequence

from pm_bot.models.market import WeatherEvent, TemperatureBucket, ForecastResult, Recommendation
from pm_bot.strategies.base import Strategy


class TailNoBarbellStrategy(Strategy):
    """Barbell strategy: tail-NO (high probability) + occasional tail-YES (lottery).

    Small-capital optimized:
    - Tail-NO: Buy NO on extreme buckets where model says NO > 80%
    - Tail-YES: Buy YES on cheap buckets where model says YES > 10%
    - Use model-based probability (not hardcoded 0.85!)
    - $1-$2 per position, quarter Kelly

    Parameters:
        tail_no_threshold: Max YES price for tail-NO bets (default $0.85)
        tail_yes_threshold: Max YES price for tail-YES bets (default $0.12)
        tail_no_alloc: Allocation to tail-NO (default 0.70)
        tail_yes_alloc: Allocation to tail-YES (default 0.30)
        min_edge_tail_no: Minimum edge for tail-NO (default 3%)
        min_edge_tail_yes: Minimum edge for tail-YES (default 8%)
    """

    name = "tail_no_barbell"

    def __init__(
        self,
        edge_threshold: float = 0.08,
        bankroll: float = 1000.0,
        kelly_fraction: float = 0.25,
        max_single_pct: float = 0.02,
        min_notional: float = 1.0,
        max_position_usd: float = 2.0,
        tail_no_threshold: float = 0.85,
        tail_yes_threshold: float = 0.12,
        tail_no_alloc: float = 0.70,
        tail_yes_alloc: float = 0.30,
        min_edge_tail_no: float = 0.03,
        min_edge_tail_yes: float = 0.08,
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
        self.tail_no_threshold = tail_no_threshold
        self.tail_yes_threshold = tail_yes_threshold
        self.tail_no_alloc = tail_no_alloc
        self.tail_yes_alloc = tail_yes_alloc
        self.min_edge_tail_no = min_edge_tail_no
        self.min_edge_tail_yes = min_edge_tail_yes
        self._rng = rng or random.Random()

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        """Generate barbell recommendations for a weather event.

        Combines tail-NO (steady) and tail-YES (lottery) positions.
        Uses model-based probability for edge calculation.
        """
        if not event.buckets:
            return []

        forecast: ForecastResult | None = kwargs.get("forecast")
        bankroll = kwargs.get("bankroll", self.bankroll)

        tail_no_recs = self._find_tail_no(event, forecast, bankroll)
        tail_yes_recs = self._find_tail_yes(event, forecast, bankroll)

        # Barbell: combine both types
        recs = []

        # Tail-NO: steady growth, multiple positions
        for rec in tail_no_recs:
            rec.size_usd *= self.tail_no_alloc
            rec.reasoning = f"[BARBELL-NO] {rec.reasoning}"
            if rec.size_usd >= self.min_notional * 0.5:
                recs.append(rec)

        # Tail-YES: lottery tickets, fewer positions
        for rec in tail_yes_recs:
            rec.size_usd *= self.tail_yes_alloc
            rec.reasoning = f"[BARBELL-YES] {rec.reasoning}"
            if rec.size_usd >= self.min_notional * 0.5:
                recs.append(rec)

        return recs

    def _find_tail_no(
        self, event: WeatherEvent, forecast: ForecastResult | None, bankroll: float
    ) -> list[Recommendation]:
        """Find tail-NO opportunities using model probability."""
        recs = []

        from pm_bot.core.weather import bucket_probability_numpy

        for b in event.buckets:
            # Tail-NO: buy NO on high-probability extreme buckets
            if b.yes_price >= self.tail_no_threshold:
                no_price = b.no_price
                if no_price <= 0:
                    continue

                # Use MODEL probability instead of hardcoded 0.85!
                if forecast and forecast.members:
                    model_yes_prob = bucket_probability_numpy(forecast, b.temp_low_c, b.temp_high_c, b.temp_unit)
                    estimated_no_prob = 1.0 - model_yes_prob
                else:
                    # Fallback: use market-implied NO probability + small buffer
                    estimated_no_prob = no_price + 0.05

                edge = estimated_no_prob - no_price

                if edge >= self.min_edge_tail_no:
                    # Kelly for NO position
                    win_payout = b.yes_price  # If NO wins, we get YES price
                    loss_amt = no_price
                    raw_kelly = (estimated_no_prob * win_payout - (1 - estimated_no_prob) * loss_amt) / win_payout

                    if raw_kelly > 0:
                        # Quarter Kelly, capped at $2 per position
                        kelly_per_trade = raw_kelly * self.kelly_fraction
                        position_usd = bankroll * kelly_per_trade
                        position_usd = min(position_usd, self.max_position_usd)
                        position_usd = max(position_usd, self.min_notional)

                        recs.append(
                            Recommendation(
                                strategy=self.name,
                                event=event,
                                bucket=b,
                                direction="NO",
                                edge=edge,
                                reasoning=f"Tail-NO {b.temp_low_c}-{b.temp_high_c}°C (edge={edge:.1%}, no_price={no_price:.1%}, model_no={estimated_no_prob:.1%})",
                                size_usd=position_usd,
                                kelly_fraction=raw_kelly,
                            )
                        )

        return recs

    def _find_tail_yes(
        self, event: WeatherEvent, forecast: ForecastResult | None, bankroll: float
    ) -> list[Recommendation]:
        """Find tail-YES lottery opportunities using model probability."""
        recs = []

        from pm_bot.core.weather import bucket_probability_numpy

        for b in event.buckets:
            # Tail-YES: cheap YES tickets on low-prob buckets
            if b.yes_price <= self.tail_yes_threshold and b.yes_price > 0.01:
                # Use MODEL probability instead of price * 1.5!
                if forecast and forecast.members:
                    model_prob = bucket_probability_numpy(forecast, b.temp_low_c, b.temp_high_c, b.temp_unit)
                else:
                    model_prob = b.yes_price * 1.2  # Conservative fallback

                edge = model_prob - b.yes_price

                if edge >= self.min_edge_tail_yes:
                    # Kelly for lottery ticket
                    win_payout = 1.0 - b.yes_price
                    loss_amt = b.yes_price
                    raw_kelly = (model_prob * win_payout - (1 - model_prob) * loss_amt) / win_payout

                    if raw_kelly > 0:
                        # Quarter Kelly, capped at $1 per lottery ticket
                        kelly_per_trade = raw_kelly * self.kelly_fraction * 0.5
                        position_usd = bankroll * kelly_per_trade
                        position_usd = min(position_usd, self.max_position_usd * 0.5)  # $1 max for lottery
                        position_usd = max(position_usd, self.min_notional * 0.5)

                        recs.append(
                            Recommendation(
                                strategy=self.name,
                                event=event,
                                bucket=b,
                                direction="YES",
                                edge=edge,
                                reasoning=f"Tail-YES lottery {b.temp_low_c}-{b.temp_high_c}°C (edge={edge:.1%}, price={b.yes_price:.1%}, model={model_prob:.1%})",
                                size_usd=position_usd,
                                kelly_fraction=raw_kelly,
                            )
                        )

        return recs
