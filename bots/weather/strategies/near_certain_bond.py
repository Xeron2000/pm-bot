"""Near-Certain Bond Strategy — buy 95-99¢ YES on near-certain outcomes.

Collects 1-5¢ daily yield per trade. Model must confirm ≥98% probability.
Uses higher Kelly fraction (0.50) and larger position ($5) because risk is low.
"""

from __future__ import annotations

from pm_bot.core.weather import bucket_probability_numpy
from pm_bot.models.market import ForecastResult, Recommendation, WeatherEvent
from pm_bot.strategies.base import Strategy


class NearCertainBondStrategy(Strategy):
    """Buy near-certain YES buckets for daily yield."""

    name = "near_certain_bond"

    def __init__(
        self,
        edge_threshold: float = 0.01,
        bankroll: float = 1000.0,
        kelly_fraction: float = 0.50,
        max_single_pct: float = 0.02,
        min_notional: float = 1.0,
        max_position_usd: float = 5.0,
        min_yes_price: float = 0.95,
        max_yes_price: float = 0.99,
        min_model_prob: float = 0.98,
        max_per_event: int = 3,
    ):
        super().__init__(
            edge_threshold=edge_threshold,
            bankroll=bankroll,
            kelly_fraction=kelly_fraction,
            max_single_pct=max_single_pct,
            min_notional=min_notional,
            max_position_usd=max_position_usd,
        )
        self.min_yes_price = min_yes_price
        self.max_yes_price = max_yes_price
        self.min_model_prob = min_model_prob
        self.max_per_event = max_per_event

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        """Generate near-certain bond recommendations."""
        defaults = self.get_defaults()
        min_yes = kwargs.get("min_yes_price", defaults.get("min_yes_price", self.min_yes_price))
        max_yes = kwargs.get("max_yes_price", defaults.get("max_yes_price", self.max_yes_price))
        min_prob = kwargs.get("min_model_prob", defaults.get("min_model_prob", self.min_model_prob))
        bankroll = kwargs.get("bankroll", self.bankroll)
        forecast: ForecastResult | None = kwargs.get("forecast")

        if not event.buckets or forecast is None:
            return []

        candidates: list[tuple[float, float, int]] = []
        for i, b in enumerate(event.buckets):
            if not (min_yes <= b.yes_price <= max_yes):
                continue

            model_prob = bucket_probability_numpy(forecast, b.temp_low_c, b.temp_high_c, b.temp_unit)
            if model_prob < min_prob:
                continue

            edge = model_prob - b.yes_price
            if edge > 0:
                candidates.append((edge, model_prob, i))

        if not candidates:
            return []

        candidates.sort(key=lambda x: x[0], reverse=True)
        candidates = candidates[: self.max_per_event]

        recs: list[Recommendation] = []
        for edge, model_prob, idx in candidates:
            b = event.buckets[idx]
            win_payout = 1.0 - b.yes_price
            loss_amt = b.yes_price
            raw_kelly = (model_prob * win_payout - (1 - model_prob) * loss_amt) / win_payout
            if raw_kelly <= 0:
                continue

            kelly_size = raw_kelly * self.kelly_fraction
            position_usd = bankroll * kelly_size / len(candidates)
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
                        f"Near-certain bond {b.temp_low_c}-{b.temp_high_c}°C "
                        f"(edge={edge:.1%}, price={b.yes_price:.1%}, model={model_prob:.1%})"
                    ),
                    size_usd=position_usd,
                    kelly_fraction=raw_kelly,
                )
            )

        return recs
