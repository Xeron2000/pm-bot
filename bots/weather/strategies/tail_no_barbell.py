"""
Tail-NO Barbell Strategy for $100 Aggressive Snowball.

Inspired by Hans323's approach: a barbell strategy that combines
small tail-YES lottery tickets (high risk, high reward) with
larger tail-NO positions (low risk, steady returns).

The idea: tail-NO bets (buying NO on extreme buckets like <65 or >95)
have ~80-90% win probability but only pay 10-20 cents per share.
Combined with occasional tail-YES lottery tickets, this creates a
barbell with both stability and upside.

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
    """
    Barbell strategy: tail-NO (high probability) + occasional tail-YES (lottery).

    Allocates ~70% of capital to tail-NO bets (steady growth)
    and ~30% to tail-YES lottery tickets (big upside).

    Parameters:
        tail_no_threshold: Max YES price for tail-NO bets (default $0.85)
        tail_yes_threshold: Max YES price for tail-YES bets (default $0.12)
        tail_no_alloc: Allocation to tail-NO (default 0.70)
        tail_yes_alloc: Allocation to tail-YES (default 0.30)
        min_edge_tail_no: Minimum edge for tail-NO (default 0.03)
        min_edge_tail_yes: Minimum edge for tail-YES (default 0.05)
    """

    name = "tail_no_barbell"

    def __init__(
        self,
        edge_threshold: float = 0.03,
        bankroll: float = 100.0,
        kelly_fraction: float = 0.60,
        max_single_pct: float = 0.50,
        min_notional: float = 0.50,
        tail_no_threshold: float = 0.85,
        tail_yes_threshold: float = 0.12,
        tail_no_alloc: float = 0.70,
        tail_yes_alloc: float = 0.30,
        min_edge_tail_no: float = 0.03,
        min_edge_tail_yes: float = 0.05,
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
        self.tail_no_threshold = tail_no_threshold
        self.tail_yes_threshold = tail_yes_threshold
        self.tail_no_alloc = tail_no_alloc
        self.tail_yes_alloc = tail_yes_alloc
        self.min_edge_tail_no = min_edge_tail_no
        self.min_edge_tail_yes = min_edge_tail_yes
        self._rng = rng or random.Random()

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        """
        Generate barbell recommendations for a weather event.

        Combines tail-NO (steady) and tail-YES (lottery) positions.
        """
        if not event.buckets:
            return []

        tail_no_recs = self._find_tail_no(event)
        tail_yes_recs = self._find_tail_yes(event)

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

    def _find_tail_no(self, event: WeatherEvent) -> list[Recommendation]:
        """Find tail-NO opportunities (buy NO on extreme buckets)."""
        recs = []

        for b in event.buckets:
            # Tail-NO: we want NO on high-probability extreme buckets
            # High YES price = cheap NO opportunity
            if b.yes_price >= self.tail_no_threshold:
                # This is a tail-NO candidate
                no_price = b.no_price
                if no_price <= 0:
                    continue

                # Edge: YES is overpriced relative to our estimate
                # For tail buckets, we estimate ~80-90% NO probability
                estimated_no_prob = 0.85  # Conservative estimate for tail-NO
                edge = estimated_no_prob - no_price

                if edge >= self.min_edge_tail_no:
                    # Kelly for NO position
                    win_payout = b.yes_price  # If NO wins, we get YES price
                    loss_amt = no_price
                    raw_kelly = (estimated_no_prob * win_payout - (1 - estimated_no_prob) * loss_amt) / win_payout

                    if raw_kelly > 0:
                        capped_kelly = min(raw_kelly * self.kelly_fraction, self.max_single_pct)
                        position_size = max(self.bankroll * capped_kelly, self.min_notional)
                        position_size = min(position_size, self.bankroll)

                        recs.append(Recommendation(
                            strategy=self.name,
                            event=event,
                            bucket=b,
                            direction="NO",
                            edge=edge,
                            reasoning=f"Tail-NO {b.temp_low_c}-{b.temp_high_c}°C (edge={edge:.1%}, no_price={no_price:.1%})",
                            size_usd=position_size,
                            kelly_fraction=raw_kelly,
                        ))

        return recs

    def _find_tail_yes(self, event: WeatherEvent) -> list[Recommendation]:
        """Find tail-YES lottery opportunities."""
        recs = []

        for b in event.buckets:
            # Tail-YES: cheap YES tickets on low-prob buckets
            if b.yes_price <= self.tail_yes_threshold and b.yes_price > 0.01:
                # Edge: we estimate slightly higher probability for tail buckets
                estimated_prob = b.yes_price * 1.5  # Optimistic estimate
                edge = estimated_prob - b.yes_price

                if edge >= self.min_edge_tail_yes:
                    # Kelly for lottery ticket
                    win_payout = 1.0 - b.yes_price
                    loss_amt = b.yes_price
                    raw_kelly = (estimated_prob * win_payout - (1 - estimated_prob) * loss_amt) / win_payout

                    if raw_kelly > 0:
                        # Smaller allocation for lottery tickets
                        capped_kelly = min(raw_kelly * self.kelly_fraction * 0.5, self.max_single_pct * 0.3)
                        position_size = max(self.bankroll * capped_kelly, self.min_notional * 0.5)
                        position_size = min(position_size, self.bankroll * 0.3)

                        recs.append(Recommendation(
                            strategy=self.name,
                            event=event,
                            bucket=b,
                            direction="YES",
                            edge=edge,
                            reasoning=f"Tail-YES lottery {b.temp_low_c}-{b.temp_high_c}°C (edge={edge:.1%}, price={b.yes_price:.1%})",
                            size_usd=position_size,
                            kelly_fraction=raw_kelly,
                        ))

        return recs
