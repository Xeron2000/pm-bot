from __future__ import annotations

import structlog

from pm_bot.models.market import ForecastResult, Recommendation, TemperatureBucket, WeatherEvent
from pm_bot.strategies.base import Strategy

log = structlog.get_logger()


class MetarObservationStrategy(Strategy):
    name = "metar_obs"

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        hours_to_resolution = kwargs.get("hours_to_resolution")
        if hours_to_resolution is None or hours_to_resolution > 12:
            return []

        metar_obs = kwargs.get("metar_observation")
        forecast = kwargs.get("forecast")
        if not metar_obs or not forecast:
            return []

        defaults = self.get_defaults()
        bankroll = kwargs.get("bankroll", defaults.get("bankroll", 100.0))

        obs_temp_c: float = metar_obs.get("temp_c", 0.0)
        forecast_mean = forecast.mean
        delta = obs_temp_c - forecast_mean

        if abs(delta) < 1.0:
            return []

        recs: list[Recommendation] = []
        shift_c = delta * 0.5

        for b in event.buckets:
            if b.yes_price <= 0 or b.no_price <= 0:
                continue
            if b.is_low_tail or b.is_high_tail:
                continue

            if delta > 0:
                if b.temp_center_c > forecast_mean + 1.0:
                    adjusted_prob = self._shifted_prob(forecast, b, shift_c)
                    edge = adjusted_prob - b.yes_price
                    if edge > 0.02:
                        size = bankroll * min(edge * 2, 0.02)
                        recs.append(Recommendation(
                            strategy=self.name,
                            event=event,
                            bucket=b,
                            direction="YES",
                            edge=edge,
                            reasoning=f"OBS {obs_temp_c:.1f}°C > FCST {forecast_mean:.1f}°C by +{delta:.1f}°C, shift +{shift_c:.1f}°C",
                            size_usd=size,
                            kelly_fraction=edge / (1.0 - b.yes_price) * 0.25,
                        ))
                elif b.temp_center_c < forecast_mean - 2.0:
                    adjusted_prob = self._shifted_prob(forecast, b, shift_c)
                    no_edge = (1.0 - adjusted_prob) - b.no_price
                    if no_edge > 0.02:
                        size = bankroll * min(no_edge * 2, 0.02)
                        recs.append(Recommendation(
                            strategy=self.name,
                            event=event,
                            bucket=b,
                            direction="NO",
                            edge=no_edge,
                            reasoning=f"OBS {obs_temp_c:.1f}°C > FCST {forecast_mean:.1f}°C by +{delta:.1f}°C, lower bucket NO",
                            size_usd=size,
                            kelly_fraction=no_edge / b.no_price * 0.25,
                        ))
            else:
                if b.temp_center_c < forecast_mean - 1.0:
                    adjusted_prob = self._shifted_prob(forecast, b, shift_c)
                    edge = adjusted_prob - b.yes_price
                    if edge > 0.02:
                        size = bankroll * min(edge * 2, 0.02)
                        recs.append(Recommendation(
                            strategy=self.name,
                            event=event,
                            bucket=b,
                            direction="YES",
                            edge=edge,
                            reasoning=f"OBS {obs_temp_c:.1f}°C < FCST {forecast_mean:.1f}°C by {delta:.1f}°C, shift {shift_c:.1f}°C",
                            size_usd=size,
                            kelly_fraction=edge / (1.0 - b.yes_price) * 0.25,
                        ))
                elif b.temp_center_c > forecast_mean + 2.0:
                    adjusted_prob = self._shifted_prob(forecast, b, shift_c)
                    no_edge = (1.0 - adjusted_prob) - b.no_price
                    if no_edge > 0.02:
                        size = bankroll * min(no_edge * 2, 0.02)
                        recs.append(Recommendation(
                            strategy=self.name,
                            event=event,
                            bucket=b,
                            direction="NO",
                            edge=no_edge,
                            reasoning=f"OBS {obs_temp_c:.1f}°C < FCST {forecast_mean:.1f}°C by {delta:.1f}°C, upper bucket NO",
                            size_usd=size,
                            kelly_fraction=no_edge / b.no_price * 0.25,
                        ))

        return recs

    def _shifted_prob(self, forecast: ForecastResult, bucket: TemperatureBucket, shift_c: float) -> float:
        from pm_bot.core.weather import bucket_probability_numpy
        shifted = ForecastResult(
            city=forecast.city,
            date=forecast.date,
            model=forecast.model,
            temp_high_c=forecast.temp_high_c + shift_c,
            members=[m + shift_c for m in forecast.members] if forecast.members else [],
        )
        return bucket_probability_numpy(shifted, bucket.temp_low_c, bucket.temp_high_c)
