from __future__ import annotations

import structlog

from pm_bot.models.market import ForecastResult, Recommendation, TemperatureBucket, WeatherEvent
from pm_bot.strategies.base import Strategy

log = structlog.get_logger()


class NegRiskSumStrategy(Strategy):
    name = "neg_risk_sum"

    TAKER_FEE_RATE_BPS = 50
    TAKER_FEE_EXPONENT = 0.5
    TAKER_FEE_MAX = 0.0125

    def _taker_fee(self, price: float) -> float:
        from pm_bot.core.clob import compute_v2_taker_fee
        return min(compute_v2_taker_fee(self.TAKER_FEE_RATE_BPS, price, self.TAKER_FEE_EXPONENT), self.TAKER_FEE_MAX)

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        defaults = self.get_defaults()
        bankroll = kwargs.get("bankroll", defaults.get("bankroll", 100.0))

        active_buckets = [b for b in event.buckets if b.yes_price > 0 or b.no_price > 0]
        if not active_buckets:
            return []

        sum_yes = sum(b.yes_price for b in active_buckets)
        recs: list[Recommendation] = []

        if sum_yes < 0.98:
            net_edge = 1.0 - sum_yes - self._taker_fee(0.5) * sum_yes
            if net_edge > 0.01:
                for b in active_buckets:
                    if b.yes_price <= 0:
                        continue
                    size = bankroll * 0.25 * net_edge / len(active_buckets)
                    recs.append(Recommendation(
                        strategy=self.name,
                        event=event,
                        bucket=b,
                        direction="YES",
                        edge=net_edge / len(active_buckets),
                        reasoning=f"ΣYES={sum_yes:.3f} < 0.98, risk-free arb (net edge={net_edge:.3f} after fees)",
                        size_usd=size,
                        kelly_fraction=net_edge / len(active_buckets) / (1.0 - b.yes_price) * 0.25,
                    ))

        elif sum_yes > 1.03:
            forecast = kwargs.get("forecast")
            if forecast is None:
                excess = sum_yes - 1.0
                net_excess = excess * (1.0 - self._taker_fee(0.5))
                if net_excess > 0.01:
                    top = sorted(active_buckets, key=lambda b: b.yes_price, reverse=True)[:3]
                    for b in top:
                        if b.no_price < 0.01:
                            continue
                        share = b.yes_price / sum_yes
                        size = bankroll * 0.25 * net_excess * share
                        recs.append(Recommendation(
                            strategy=self.name,
                            event=event,
                            bucket=b,
                            direction="NO",
                            edge=net_excess * share,
                            reasoning=f"ΣYES={sum_yes:.3f} > 1.03, no forecast; buying NO on top bucket by YES price",
                            size_usd=size,
                            kelly_fraction=net_excess * share * 0.25,
                        ))
            else:
                overpriced = self._find_overpriced(active_buckets, forecast)
                for b, model_prob in overpriced[:3]:
                    no_edge = (1.0 - model_prob) - b.no_price
                    if no_edge > 0.01:
                        net_edge = no_edge * (1.0 - self._taker_fee(b.yes_price))
                        size = bankroll * 0.25 * net_edge
                        recs.append(Recommendation(
                            strategy=self.name,
                            event=event,
                            bucket=b,
                            direction="NO",
                            edge=net_edge,
                            reasoning=f"ΣYES={sum_yes:.3f} > 1.03, overpriced bucket (YES={b.yes_price:.2f}, model={model_prob:.2f})",
                            size_usd=size,
                            kelly_fraction=net_edge / b.no_price * 0.25,
                        ))

        return recs

    def _find_overpriced(
        self,
        buckets: list[TemperatureBucket],
        forecast: ForecastResult,
    ) -> list[tuple[TemperatureBucket, float]]:
        from pm_bot.core.weather import bucket_probability_numpy
        result: list[tuple[TemperatureBucket, float]] = []
        for b in buckets:
            if b.yes_price > 0:
                model_prob = bucket_probability_numpy(forecast, b.temp_low_c, b.temp_high_c, b.temp_unit)
                if b.yes_price > model_prob + 0.01:
                    result.append((b, model_prob))
        result.sort(key=lambda x: x[0].yes_price - x[1], reverse=True)
        return result
