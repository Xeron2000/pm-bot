"""Barbell strategy inspired by ColdMath's approach.

Combines:
1. Many small tail positions ($50-$150 per bucket) - safety
2. Occasional high-conviction central bucket bets - upside

Reference:
- ColdMath: $120K+ profit from weather markets
- Barbell approach: "many small tail positions with occasional high-conviction bets"

The key insight: tail buckets have positive expected value due to favorite-longshot bias,
but central buckets can also have edge when the model strongly disagrees with market.
"""

from __future__ import annotations

from pm_bot.core.emos import EMOSCalibrator, bucket_probability_emos
from pm_bot.core.weather import bucket_probability_numpy
from pm_bot.models.market import ForecastResult, Recommendation, WeatherEvent
from pm_bot.strategies.base import Strategy


class BarbellStrategy(Strategy):
    """Barbell strategy: tail buys + high-conviction central bets.

    Position allocation:
    - 80% to tail buckets (price < $0.15) with small positions
    - 20% to central buckets with strong model disagreement

    This balances safety (tail buys have limited downside) with
    upside (central bets can have larger payoffs).
    """

    name = "barbell"

    # Tail parameters
    MAX_TAIL_PRICE = 0.15
    TAIL_KELLY = 0.15  # More conservative Kelly for tails
    TAIL_MAX_POSITION = 2.0  # Max $2 per tail position

    # Central bucket parameters
    CENTRAL_MIN_EDGE = 0.20  # Need 20%+ edge for central buckets
    CENTRAL_KELLY = 0.10  # Very conservative for central
    CENTRAL_MAX_POSITION = 5.0  # Can go up to $5 for high conviction

    def __init__(
        self,
        edge_threshold: float = 0.08,
        bankroll: float = 1000.0,
        kelly_fraction: float = 0.25,
        max_single_pct: float = 0.02,
        min_notional: float = 1.0,
        max_position_usd: float = 5.0,
        tail_ratio: float = 0.80,
        emos_calibrator: EMOSCalibrator | None = None,
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
        self.tail_ratio = tail_ratio
        self.emos_calibrator = emos_calibrator

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        """Run barbell strategy.

        Args:
            event: Weather event with buckets
            kwargs: Must include 'forecast' and optionally 'emos_calibrator'

        Returns:
            List of recommendations (tail buys + central bets)
        """
        forecast: ForecastResult | None = kwargs.get("forecast")
        bankroll = kwargs.get("bankroll", self.bankroll)
        calibrator = kwargs.get("emos_calibrator", self.emos_calibrator)

        if not forecast or not forecast.members:
            return []

        # Separate tail and central buckets
        tail_buckets = []
        central_buckets = []

        for b in event.buckets:
            if b.yes_price <= 0:
                continue

            if b.yes_price < self.MAX_TAIL_PRICE:
                tail_buckets.append(b)
            else:
                central_buckets.append(b)

        recs: list[Recommendation] = []

        # Process tail buckets (many small positions)
        for b in tail_buckets:
            model_prob = self._get_model_prob(forecast, b, calibrator)

            # Filter: model must say bucket has real probability
            if model_prob < 0.18:
                continue

            edge = model_prob - b.yes_price
            if edge < self.edge_threshold:
                continue

            # Conservative Kelly for tails
            win_payout = 1.0 - b.yes_price
            loss_amt = b.yes_price
            raw_kelly = (model_prob * win_payout - (1 - model_prob) * loss_amt) / win_payout

            if raw_kelly <= 0:
                continue

            # Apply tail Kelly (more conservative)
            position_usd = bankroll * raw_kelly * self.TAIL_KELLY
            position_usd = min(position_usd, self.TAIL_MAX_POSITION)
            position_usd = max(position_usd, self.min_notional)

            recs.append(
                Recommendation(
                    strategy=self.name,
                    event=event,
                    bucket=b,
                    direction="YES",
                    edge=edge,
                    reasoning=(
                        f"BARBELL-TAIL YES@{b.yes_price:.2f}, "
                        f"model={model_prob:.1%}, edge={edge:.1%}"
                    ),
                    size_usd=position_usd,
                    kelly_fraction=raw_kelly,
                )
            )

        # Process central buckets (occasional high-conviction bets)
        for b in central_buckets:
            model_prob = self._get_model_prob(forecast, b, calibrator)

            # Need strong edge for central buckets
            edge = model_prob - b.yes_price
            if edge < self.CENTRAL_MIN_EDGE:
                continue

            # Also check for YES direction (model > market by large margin)
            if b.yes_price >= 0.30 and edge >= self.CENTRAL_MIN_EDGE:
                # High conviction YES bet
                win_payout = 1.0 - b.yes_price
                loss_amt = b.yes_price
                raw_kelly = (model_prob * win_payout - (1 - model_prob) * loss_amt) / win_payout

                if raw_kelly <= 0:
                    continue

                position_usd = bankroll * raw_kelly * self.CENTRAL_KELLY
                position_usd = min(position_usd, self.CENTRAL_MAX_POSITION)
                position_usd = max(position_usd, self.min_notional)

                recs.append(
                    Recommendation(
                        strategy=self.name,
                        event=event,
                        bucket=b,
                        direction="YES",
                        edge=edge,
                        reasoning=(
                            f"BARBELL-CENTRAL YES@{b.yes_price:.2f}, "
                            f"model={model_prob:.1%}, edge={edge:.1%}"
                        ),
                        size_usd=position_usd,
                        kelly_fraction=raw_kelly,
                    )
                )

            # Check for NO direction (market overprices bucket)
            no_price = 1.0 - b.yes_price
            no_edge = (1.0 - model_prob) - no_price
            if no_price > 0.30 and no_edge >= self.CENTRAL_MIN_EDGE:
                win_payout = 1.0 - no_price
                loss_amt = no_price
                raw_kelly = ((1.0 - model_prob) * win_payout - model_prob * loss_amt) / win_payout

                if raw_kelly <= 0:
                    continue

                position_usd = bankroll * raw_kelly * self.CENTRAL_KELLY
                position_usd = min(position_usd, self.CENTRAL_MAX_POSITION)
                position_usd = max(position_usd, self.min_notional)

                recs.append(
                    Recommendation(
                        strategy=self.name,
                        event=event,
                        bucket=b,
                        direction="NO",
                        edge=no_edge,
                        reasoning=(
                            f"BARBELL-CENTRAL NO@{no_price:.2f}, "
                            f"model={1.0-model_prob:.1%}, edge={no_edge:.1%}"
                        ),
                        size_usd=position_usd,
                        kelly_fraction=raw_kelly,
                    )
                )

        # Sort by edge
        recs.sort(key=lambda r: r.edge, reverse=True)

        # Limit total recommendations per event
        return recs[:5]

    def _get_model_prob(
        self,
        forecast: ForecastResult,
        bucket,
        calibrator: EMOSCalibrator | None,
    ) -> float:
        """Get model probability for a bucket."""
        if calibrator and calibrator._trained:
            return bucket_probability_emos(
                calibrator,
                forecast.members,
                bucket.temp_low_c,
                bucket.temp_high_c,
                bucket.temp_unit,
            )
        else:
            return bucket_probability_numpy(
                forecast,
                bucket.temp_low_c,
                bucket.temp_high_c,
                bucket.temp_unit,
            )


class AdaptiveBarbellStrategy(BarbellStrategy):
    """Adaptive barbell that adjusts tail/central ratio based on market conditions.

    - High tail bucket count: increase tail allocation
    - Strong model disagreement: increase central allocation
    - Low liquidity: reduce all positions
    """

    name = "adaptive_barbell"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.min_tail_buckets = 2
        self.max_tail_buckets = 8

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        """Run adaptive barbell strategy."""
        forecast: ForecastResult | None = kwargs.get("forecast")
        if not forecast or not forecast.members:
            return []

        # Count tail buckets
        tail_count = sum(
            1 for b in event.buckets
            if 0 < b.yes_price < self.MAX_TAIL_PRICE
        )

        # Adjust tail ratio based on tail count
        if tail_count >= self.max_tail_buckets:
            # Many tail buckets: increase tail allocation
            self.tail_ratio = 0.90
        elif tail_count <= self.min_tail_buckets:
            # Few tail buckets: decrease tail allocation
            self.tail_ratio = 0.60
        else:
            # Normal allocation
            self.tail_ratio = 0.80

        return super().run(event, **kwargs)
