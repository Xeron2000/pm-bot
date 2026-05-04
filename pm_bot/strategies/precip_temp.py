from __future__ import annotations

import structlog

from pm_bot.models.market import ForecastResult, Recommendation, WeatherEvent
from pm_bot.strategies.base import Strategy

log = structlog.get_logger()


class PrecipTempCorrelationStrategy(Strategy):
    name = "precip_temp"

    HIGH_PRECIP_THRESHOLD = 0.70
    LOW_PRECIP_THRESHOLD = 0.10

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        precip_forecast = kwargs.get("precip_forecast")
        forecast = kwargs.get("forecast")
        if precip_forecast is None or not forecast:
            return []

        defaults = self.get_defaults()
        bankroll = kwargs.get("bankroll", defaults.get("bankroll", 100.0))

        precip_prob: float = float(precip_forecast)
        recs: list[Recommendation] = []

        if precip_prob > self.HIGH_PRECIP_THRESHOLD:
            shift_c = -1.5
            spread_factor = 0.85
            adjusted = self._adjusted_forecast(forecast, shift_c, spread_factor)
        elif precip_prob < self.LOW_PRECIP_THRESHOLD:
            shift_c = 0.75
            spread_factor = 1.10
            adjusted = self._adjusted_forecast(forecast, shift_c, spread_factor)
        else:
            return recs

        from pm_bot.core.weather import bucket_probability_numpy

        for b in event.buckets:
            if b.yes_price <= 0 or b.no_price <= 0:
                continue

            adjusted_prob = bucket_probability_numpy(adjusted, b.temp_low_c, b.temp_high_c)

            if adjusted_prob > b.yes_price + 0.02:
                edge = adjusted_prob - b.yes_price
                recs.append(Recommendation(
                    strategy=self.name,
                    event=event,
                    bucket=b,
                    direction="YES",
                    edge=edge,
                    reasoning=(
                        f"precip={precip_prob:.0%}, "
                        f"shift={'↓' if shift_c < 0 else '↑'}{abs(shift_c):.1f}°C, "
                        f"spread×{spread_factor:.2f}, "
                        f"adj_prob={adjusted_prob:.2f} vs mkt={b.yes_price:.2f}"
                    ),
                    size_usd=bankroll * min(edge, 0.015),
                    kelly_fraction=edge / (1.0 - b.yes_price) * 0.25,
                ))

            no_edge = (1.0 - adjusted_prob) - b.no_price
            if no_edge > 0.02:
                recs.append(Recommendation(
                    strategy=self.name,
                    event=event,
                    bucket=b,
                    direction="NO",
                    edge=no_edge,
                    reasoning=(
                        f"precip={precip_prob:.0%}, "
                        f"shift={'↓' if shift_c < 0 else '↑'}{abs(shift_c):.1f}°C, "
                        f"spread×{spread_factor:.2f}, "
                        f"adj_prob={adjusted_prob:.2f} vs NO mkt={b.no_price:.2f}"
                    ),
                    size_usd=bankroll * min(no_edge, 0.015),
                    kelly_fraction=no_edge / b.no_price * 0.25,
                ))

        return recs

    def _adjusted_forecast(self, forecast: ForecastResult, shift_c: float, spread_factor: float) -> ForecastResult:
        members = forecast.members if forecast.members else [forecast.temp_high_c]
        shifted_mean = forecast.temp_high_c + shift_c
        current_mean = sum(members) / len(members) if members else forecast.temp_high_c
        new_members = []
        for m in members:
            dev = m - current_mean
            new_members.append(shifted_mean + dev * spread_factor)

        return ForecastResult(
            city=forecast.city,
            date=forecast.date,
            model="precip_adjusted",
            temp_high_c=shifted_mean,
            members=new_members,
        )
