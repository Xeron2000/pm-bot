from __future__ import annotations

import structlog

from pm_bot.models.market import ForecastResult, Recommendation, TemperatureBucket, WeatherEvent
from pm_bot.strategies.base import Strategy

log = structlog.get_logger()


class ResolutionDivergenceStrategy(Strategy):
    name = "resolution_div"

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        forecast = kwargs.get("forecast")
        if not forecast:
            return []

        defaults = self.get_defaults()
        bankroll = kwargs.get("bankroll", defaults.get("bankroll", 100.0))

        is_dst = self._is_dst_month(event.date)
        is_frontal = kwargs.get("frontal_passage", False)

        wu_probs = self._compute_wu_probs(forecast, event.buckets, is_dst)
        nws_probs = self._compute_nws_probs(forecast, event.buckets, is_dst, is_frontal)

        confidence = 0.5
        if is_dst:
            confidence += 0.2
        if is_frontal:
            confidence += 0.3
        confidence = min(confidence, 1.0)

        recs: list[Recommendation] = []
        for i, b in enumerate(event.buckets):
            if b.yes_price <= 0 or b.no_price <= 0:
                continue

            wu_p = wu_probs.get(i, 0.5)
            nws_p = nws_probs.get(i, 0.5)
            diverged = abs(wu_p - nws_p)

            if diverged < 0.03:
                continue

            edge = diverged * confidence

            if wu_p > nws_p:
                if wu_p > b.yes_price + 0.02:
                    recs.append(Recommendation(
                        strategy=self.name,
                        event=event,
                        bucket=b,
                        direction="YES",
                        edge=edge,
                        reasoning=f"WU prob {wu_p:.2f} > NWS {nws_p:.2f} (Δ={diverged:.2f}), market={b.yes_price:.2f}, dst={is_dst}, front={is_frontal}",
                        size_usd=bankroll * min(edge, 0.015),
                        kelly_fraction=edge / (1.0 - b.yes_price) * 0.25,
                    ))
            else:
                if wu_p < b.yes_price - 0.02:
                    no_edge = (1.0 - wu_p) - b.no_price
                    if no_edge > 0.02:
                        recs.append(Recommendation(
                            strategy=self.name,
                            event=event,
                            bucket=b,
                            direction="NO",
                            edge=no_edge * confidence,
                            reasoning=f"WU prob {wu_p:.2f} < NWS {nws_p:.2f} (Δ={diverged:.2f}), market NO={b.no_price:.2f}, dst={is_dst}, front={is_frontal}",
                            size_usd=bankroll * min(no_edge * confidence, 0.015),
                            kelly_fraction=no_edge / b.no_price * 0.25,
                        ))

        return recs

    def _is_dst_month(self, date_str: str) -> bool:
        try:
            month = int(date_str.split("-")[1])
            return 3 <= month <= 11
        except (ValueError, IndexError):
            return False

    def _compute_wu_probs(
        self,
        forecast: ForecastResult,
        buckets: list[TemperatureBucket],
        is_dst: bool,
    ) -> dict[int, float]:
        from pm_bot.core.weather import bucket_probability_numpy
        probs: dict[int, float] = {}
        for i, b in enumerate(buckets):
            low = b.temp_low_c
            high = b.temp_high_c
            probs[i] = bucket_probability_numpy(forecast, low, high, b.temp_unit)
        return probs

    def _compute_nws_probs(
        self,
        forecast: ForecastResult,
        buckets: list[TemperatureBucket],
        is_dst: bool,
        is_frontal: bool,
    ) -> dict[int, float]:
        from pm_bot.core.weather import bucket_probability_numpy
        nws_forecast = ForecastResult(
            city=forecast.city,
            date=forecast.date,
            model="nws_adjusted",
            temp_high_c=forecast.temp_high_c,
            members=list(forecast.members) if forecast.members else [],
        )
        if is_dst:
            for i in range(len(nws_forecast.members)):
                nws_forecast.members[i] -= 0.3
            nws_forecast.temp_high_c -= 0.3

        if is_frontal:
            nws_forecast.temp_high_c += 0.5

        probs: dict[int, float] = {}
        for i, b in enumerate(buckets):
            low = b.temp_low_c
            high = b.temp_high_c
            probs[i] = bucket_probability_numpy(nws_forecast, low, high, b.temp_unit)
        return probs
