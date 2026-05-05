from __future__ import annotations

import structlog

from pm_bot.models.market import ForecastResult, Recommendation, WeatherEvent
from pm_bot.strategies.base import Strategy

log = structlog.get_logger()


class TruncationEdgeStrategy(Strategy):
    name = "truncation_edge"

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        defaults = self.get_defaults()
        edge_min = kwargs.get("edge_min", defaults.get("edge_min", 0.03))
        forecast: ForecastResult | None = kwargs.get("forecast")
        recs: list[Recommendation] = []

        if not forecast:
            return recs

        from pm_bot.core.weather import bucket_probability_numpy

        for b in event.buckets:
            if b.yes_price <= 0.01 or b.yes_price >= 0.99:
                continue

            model_prob = bucket_probability_numpy(forecast, b.temp_low_c, b.temp_high_c, b.temp_unit)

            if model_prob <= 0:
                continue

            yes_edge = model_prob - b.yes_price
            no_edge = (1.0 - model_prob) - b.no_price

            if b.temp_low_c != float("-inf") and b.temp_high_c != float("inf"):
                mean_val = forecast.mean
                if b.temp_unit == "F":
                    mean_val = mean_val * 1.8 + 32.0
                fractional_part = mean_val % 1.0
                near_boundary = fractional_part > 0.7 or fractional_part < 0.3
            else:
                near_boundary = False

            if near_boundary and yes_edge >= edge_min:
                recs.append(
                    Recommendation(
                        strategy=self.name,
                        event=event,
                        bucket=b,
                        direction="YES",
                        edge=yes_edge,
                        reasoning=f"truncation edge near boundary (forecast={forecast.mean:.1f}°C, frac={fractional_part:.2f}), model_prob={model_prob:.2f}, market={b.yes_price:.2f}",
                    )
                )

            if near_boundary and no_edge >= edge_min:
                recs.append(
                    Recommendation(
                        strategy=self.name,
                        event=event,
                        bucket=b,
                        direction="NO",
                        edge=no_edge,
                        reasoning=f"truncation edge near boundary (forecast={forecast.mean:.1f}°C, frac={fractional_part:.2f}), model_prob={model_prob:.2f}, NO_edge={no_edge:.2f}",
                    )
                )

            if yes_edge >= edge_min * 2 and not near_boundary:
                recs.append(
                    Recommendation(
                        strategy=self.name,
                        event=event,
                        bucket=b,
                        direction="YES",
                        edge=yes_edge,
                        reasoning=f"truncation-aware model_prob={model_prob:.2f} vs market={b.yes_price:.2f}, edge={yes_edge:.2f}",
                    )
                )

            if no_edge >= edge_min * 2 and not near_boundary:
                recs.append(
                    Recommendation(
                        strategy=self.name,
                        event=event,
                        bucket=b,
                        direction="NO",
                        edge=no_edge,
                        reasoning=f"truncation-aware model_prob={model_prob:.2f}, NO_edge={no_edge:.2f}",
                    )
                )

        return recs
