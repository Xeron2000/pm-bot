from __future__ import annotations

from pm_bot.models.market import Recommendation, TemperatureBucket, WeatherEvent
from pm_bot.models.config import STRATEGY_DEFAULTS
from pm_bot.strategies.base import Strategy


class NarrowNoStrategy(Strategy):
    name = "narrow_no"

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        defaults = STRATEGY_DEFAULTS.get(self.name, {})
        max_bucket_width_c = kwargs.get("max_bucket_width_c", defaults.get("max_bucket_width_c", 2.0))
        no_min = kwargs.get("no_min", defaults.get("no_min", 0.45))
        recs: list[Recommendation] = []

        for b in event.buckets:
            if b.yes_price <= 0 or b.no_price <= 0:
                continue

            width_c = self._bucket_width_c(b)
            if width_c is None or width_c > max_bucket_width_c:
                continue

            if b.yes_price >= no_min:
                edge = 0.8 * b.no_price - 0.2 * (1.0 - b.no_price)
                recs.append(Recommendation(
                    strategy=self.name,
                    event=event,
                    bucket=b,
                    direction="NO",
                    edge=edge,
                    reasoning=(
                        f"YES@{b.yes_price:.2f} ≥ {no_min:.2f}, "
                        f"width={width_c:.1f}°C ≤ {max_bucket_width_c:.1f}°C "
                        f"(narrow bucket: buy NO on overpriced center)"
                    ),
                ))

        return recs

    def _bucket_width_c(self, b: TemperatureBucket) -> float | None:
        if b.is_low_tail or b.is_high_tail:
            return None
        return b.temp_high_c - b.temp_low_c
