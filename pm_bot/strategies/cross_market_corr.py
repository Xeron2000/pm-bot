from __future__ import annotations

import structlog

from pm_bot.models.market import ForecastResult, Recommendation, WeatherEvent
from pm_bot.strategies.base import Strategy

log = structlog.get_logger()


class CrossMarketCorrelationStrategy(Strategy):
    name = "cross_corr"

    CORR_EXTREME_HIGH = 0.15
    CORR_CLEAR_SKY = -0.10

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        paired_events = kwargs.get("paired_events")
        forecast = kwargs.get("forecast")
        if not paired_events or not forecast:
            return []

        defaults = self.get_defaults()
        bankroll = kwargs.get("bankroll", defaults.get("bankroll", 100.0))

        paired = [e for e in paired_events if e.event_id != event.event_id and e.city == event.city and e.date == event.date]
        if not paired:
            return []

        extreme_threshold = forecast.mean + 2.0 * max(forecast.std, 1.5)
        clear_sky_threshold = forecast.mean + 1.5 * max(forecast.std, 1.5)

        is_extreme = forecast.mean >= extreme_threshold
        is_clear = forecast.mean >= clear_sky_threshold and forecast.std < 1.5

        if not is_extreme and not is_clear:
            return []

        correlation = self.CORR_EXTREME_HIGH if is_extreme else self.CORR_CLEAR_SKY
        recs: list[Recommendation] = []

        for paired_ev in paired:
            paired_forecast = kwargs.get("paired_forecast")
            if not paired_forecast:
                continue

            conditional_shift = forecast.mean - (forecast.mean - forecast.std) * (1.0 - correlation)
            conditional_mean = paired_forecast.mean + conditional_shift * 0.3

            for b in paired_ev.buckets:
                if b.yes_price <= 0 or b.no_price <= 0:
                    continue

                from pm_bot.core.weather import bucket_probability_numpy
                shifted_forecast = ForecastResult(
                    city=paired_forecast.city,
                    date=paired_forecast.date,
                    model=paired_forecast.model,
                    temp_high_c=conditional_mean,
                    members=[m + (conditional_mean - paired_forecast.mean) for m in paired_forecast.members] if paired_forecast.members else [],
                )
                cond_prob = bucket_probability_numpy(shifted_forecast, b.temp_low_c, b.temp_high_c)

                if is_extreme and correlation > 0:
                    edge = cond_prob - b.yes_price
                    if edge > 0.03:
                        recs.append(Recommendation(
                            strategy=self.name,
                            event=paired_ev,
                            bucket=b,
                            direction="YES",
                            edge=edge,
                            reasoning=f"extreme high on paired market, corr={correlation:.2f}, cond_prob={cond_prob:.2f} vs mkt={b.yes_price:.2f}",
                            size_usd=bankroll * min(edge * 0.5, 0.01),
                            kelly_fraction=edge / (1.0 - b.yes_price) * 0.25,
                        ))
                elif is_clear and correlation < 0:
                    no_edge = (1.0 - cond_prob) - b.no_price
                    if no_edge > 0.03:
                        recs.append(Recommendation(
                            strategy=self.name,
                            event=paired_ev,
                            bucket=b,
                            direction="NO",
                            edge=no_edge,
                            reasoning=f"clear sky on paired market, corr={correlation:.2f}, cond_prob={cond_prob:.2f} vs NO mkt={b.no_price:.2f}",
                            size_usd=bankroll * min(no_edge * 0.5, 0.01),
                            kelly_fraction=no_edge / b.no_price * 0.25,
                        ))

        return recs

