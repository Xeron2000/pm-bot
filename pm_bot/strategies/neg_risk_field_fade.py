from __future__ import annotations

import structlog

from pm_bot.models.market import ForecastResult, Recommendation, TemperatureBucket, WeatherEvent
from pm_bot.strategies.base import Strategy

log = structlog.get_logger()


class NegRiskFieldFadeStrategy(Strategy):
    name = "neg_risk_field_fade"

    SUM_YES_OVER_ROUND = 1.02
    TAKER_FEE_RATE_BPS = 50
    TAKER_FEE_EXPONENT = 0.5
    TAKER_FEE_MAX = 0.0125
    MAX_NO_POSITIONS = 6

    def _taker_fee(self, price: float) -> float:
        from pm_bot.core.clob import compute_v2_taker_fee
        return min(compute_v2_taker_fee(self.TAKER_FEE_RATE_BPS, price, self.TAKER_FEE_EXPONENT), self.TAKER_FEE_MAX)

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        defaults = self.get_defaults()
        bankroll = kwargs.get("bankroll", defaults.get("bankroll", 100.0))
        forecast: ForecastResult | None = kwargs.get("forecast")

        active = [b for b in event.buckets if b.yes_price > 0.005 and b.yes_price < 0.995]
        if len(active) < 4:
            return []

        sum_yes = sum(b.yes_price for b in active)
        if sum_yes < self.SUM_YES_OVER_ROUND:
            return []

        total_fee = sum(self._taker_fee(b.yes_price) for b in active)
        net_excess = sum_yes - 1.0 - total_fee
        if net_excess <= 0.005:
            return []

        overpriced = self._rank_overpriced(active, forecast)
        recs: list[Recommendation] = []

        for b, model_prob in overpriced[:self.MAX_NO_POSITIONS]:
            no_price = b.no_price
            if no_price < 0.02:
                continue

            if model_prob is not None:
                no_edge = (1.0 - model_prob) - no_price
            else:
                overpricing_ratio = b.yes_price / sum_yes
                no_edge = net_excess * overpricing_ratio

            fee = self._taker_fee(b.yes_price)
            no_edge_after_fee = no_edge - fee

            if no_edge_after_fee > 0.005:
                size = bankroll * 0.15 * no_edge_after_fee
                recs.append(Recommendation(
                    strategy=self.name,
                    event=event,
                    bucket=b,
                    direction="NO",
                    edge=no_edge_after_fee,
                    reasoning=f"ΣYES={sum_yes:.3f} over-round, NO on YES={b.yes_price:.2f}" + (f", model={model_prob:.2f}" if model_prob is not None else f", ratio={b.yes_price / sum_yes:.2f}"),
                    size_usd=size,
                    kelly_fraction=no_edge_after_fee / no_price * 0.15,
                ))

        return recs

    def _rank_overpriced(
        self,
        buckets: list[TemperatureBucket],
        forecast: ForecastResult | None,
    ) -> list[tuple[TemperatureBucket, float | None]]:
        if forecast is not None:
            from pm_bot.core.weather import bucket_probability_numpy
            ranked: list[tuple[TemperatureBucket, float | None]] = []
            for b in buckets:
                model_prob = bucket_probability_numpy(forecast, b.temp_low_c, b.temp_high_c, b.temp_unit)
                ranked.append((b, model_prob))
            ranked.sort(key=lambda x: x[0].yes_price - (x[1] or 0), reverse=True)
            return ranked
        else:
            ranked = [(b, None) for b in buckets]
            ranked.sort(key=lambda x: x[0].yes_price, reverse=True)
            return ranked
