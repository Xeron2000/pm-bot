from __future__ import annotations

import structlog

from pm_bot.models.market import ForecastResult, Recommendation, WeatherEvent
from pm_bot.strategies.base import Strategy

log = structlog.get_logger()


class EnsembleSpreadStrategy(Strategy):
    name = "ensemble_spread"

    MIN_STD_C = 1.5
    NO_ENTRY_LO = 0.20
    NO_ENTRY_HI = 0.75

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        defaults = self.get_defaults()
        edge_min = kwargs.get("edge_min", defaults.get("edge_min", 0.05))
        forecast: ForecastResult | None = kwargs.get("forecast")
        recs: list[Recommendation] = []

        if not forecast:
            return recs

        std = forecast.std
        if std < self.MIN_STD_C:
            return recs

        from pm_bot.core.weather import bucket_probability_numpy

        for b in event.buckets:
            if b.yes_price <= 0.01 or b.yes_price >= 0.99:
                continue

            model_prob = bucket_probability_numpy(forecast, b.temp_low_c, b.temp_high_c, b.temp_unit)

            yes_edge = model_prob - b.yes_price
            no_edge = (1.0 - model_prob) - b.no_price

            if yes_edge >= edge_min:
                recs.append(
                    Recommendation(
                        strategy=self.name,
                        event=event,
                        bucket=b,
                        direction="YES",
                        edge=yes_edge,
                        reasoning=f"wide spread (σ={std:.1f}°C), tail underpriced: model_prob={model_prob:.2f}, market={b.yes_price:.2f}",
                    )
                )

            if self.NO_ENTRY_LO <= b.no_price <= self.NO_ENTRY_HI and no_edge >= edge_min:
                recs.append(
                    Recommendation(
                        strategy=self.name,
                        event=event,
                        bucket=b,
                        direction="NO",
                        edge=no_edge,
                        reasoning=f"wide spread (σ={std:.1f}°C), NO entry: model_prob={model_prob:.2f}, no_price={b.no_price:.2f}, NO_edge={no_edge:.2f}",
                    )
                )

        return recs
