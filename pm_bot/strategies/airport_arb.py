from __future__ import annotations

import structlog

from pm_bot.models.market import Recommendation, TemperatureBucket, WeatherEvent
from pm_bot.models.config import STRATEGY_DEFAULTS
from pm_bot.strategies.base import Strategy
from pm_bot.core.config_loader import get_station_for_city, load_config

log = structlog.get_logger()


def _f_to_c(f: float) -> float:
    return (f - 32) / 1.8


def _c_to_f(c: float) -> float:
    return c * 1.8 + 32


class AirportArbStrategy(Strategy):
    name = "airport_arb"

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        defaults = STRATEGY_DEFAULTS.get(self.name, {})
        min_delta_f = kwargs.get("min_delta_f", defaults.get("min_delta_f", 3.0))
        recs: list[Recommendation] = []

        config = kwargs.get("config") or load_config()
        station_info = get_station_for_city(config, event.city)
        if not station_info:
            return recs

        airport_forecast = kwargs.get("airport_forecast")
        city_forecast = kwargs.get("city_forecast")

        if not airport_forecast or not city_forecast:
            return recs

        airport_temp_f = _c_to_f(airport_forecast.temp_high_c)
        city_temp_f = _c_to_f(city_forecast.temp_high_c)
        delta_f = airport_temp_f - city_temp_f

        if abs(delta_f) < min_delta_f:
            return recs

        direction: str
        if delta_f < 0:
            direction = "NO"
            target_temp_f = city_temp_f
        else:
            direction = "YES"
            target_temp_f = airport_temp_f

        target_temp_c = _f_to_c(target_temp_f)

        best_bucket: TemperatureBucket | None = None
        best_distance = float("inf")
        for b in event.buckets:
            if b.is_low_tail or b.is_high_tail:
                continue
            if b.yes_price <= 0:
                continue
            center = b.temp_center_c
            dist = abs(center - target_temp_c)
            if dist < best_distance:
                best_distance = dist
                best_bucket = b

        if best_bucket is None:
            return recs

        if direction == "NO":
            edge = 0.8 * best_bucket.no_price - 0.2 * (1.0 - best_bucket.no_price)
        else:
            edge = 0.8 * (1.0 - best_bucket.yes_price) - 0.2 * best_bucket.yes_price

        sign = "cooler" if delta_f < 0 else "warmer"
        recs.append(Recommendation(
            strategy=self.name,
            event=event,
            bucket=best_bucket,
            direction=direction,
            edge=edge,
            reasoning=(
                f"airport {sign} by {abs(delta_f):.1f}°F "
                f"(airport={airport_temp_f:.1f}°F vs city={city_temp_f:.1f}°F, "
                f"station={station_info.get('icao', '?')})"
            ),
        ))

        return recs
