from __future__ import annotations

from pm_bot.models.market import Recommendation, TemperatureBucket, WeatherEvent, ForecastResult
from pm_bot.models.config import STRATEGY_DEFAULTS


class Strategy:
    name: str = "base"

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        raise NotImplementedError

    def get_defaults(self) -> dict[str, float]:
        return STRATEGY_DEFAULTS.get(self.name, {})


class Gopfan2Strategy(Strategy):
    name = "gopfan2"

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        defaults = self.get_defaults()
        yes_max = kwargs.get("yes_max", defaults.get("yes_max", 0.15))
        no_min = kwargs.get("no_min", defaults.get("no_min", 0.45))
        recs: list[Recommendation] = []

        for b in event.buckets:
            if b.yes_price <= 0 or b.no_price <= 0:
                continue
            # Tail buckets: buy YES on cheap ones
            if b.yes_price <= yes_max:
                # gopfan2 logic: at 80% win rate, EV = 0.8*(1-p) - 0.2*p
                edge = 0.8 * (1.0 - b.yes_price) - 0.2 * b.yes_price
                recs.append(Recommendation(
                    strategy=self.name,
                    event=event,
                    bucket=b,
                    direction="YES",
                    edge=edge,
                    reasoning=f"YES@{b.yes_price:.2f} ≤ {yes_max:.2f} (gopfan2 rule: buy tail YES)",
                ))
            # Center buckets: buy NO on expensive ones (skip if already recommended YES)
            elif b.no_price >= no_min:
                # At 80% win rate for NO, EV = 0.8*no_price - 0.2*(1-no_price)
                edge = 0.8 * b.no_price - 0.2 * (1.0 - b.no_price)
                recs.append(Recommendation(
                    strategy=self.name,
                    event=event,
                    bucket=b,
                    direction="NO",
                    edge=edge,
                    reasoning=f"NO@{b.no_price:.2f} ≥ {no_min:.2f} (gopfan2 rule: buy center NO)",
                ))

        return recs


class SumArbStrategy(Strategy):
    name = "sum_arb"

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        defaults = self.get_defaults()
        gap_min = kwargs.get("gap_min", defaults.get("gap_min", 0.02))
        recs: list[Recommendation] = []

        # Skip events where all prices are 0 (settled or invalid)
        if not any(b.yes_price > 0 or b.no_price > 0 for b in event.buckets):
            return recs

        gap = event.sum_gap
        if abs(gap) >= gap_min:
            if gap > 0:
                recs.append(Recommendation(
                    strategy=self.name,
                    event=event,
                    bucket=event.buckets[0] if event.buckets else TemperatureBucket(
                        market_id="", question="", temp_low=0, temp_high=0,
                        temp_unit="C", yes_price=0, no_price=0, volume=0,
                    ),
                    direction="YES",
                    edge=gap,
                    reasoning=f"ΣYES={event.sum_yes:.3f}, gap={gap:.3f} (>+{gap_min:.2f}): buy all YES buckets for risk-free profit",
                ))
            else:
                recs.append(Recommendation(
                    strategy=self.name,
                    event=event,
                    bucket=event.buckets[0] if event.buckets else TemperatureBucket(
                        market_id="", question="", temp_low=0, temp_high=0,
                        temp_unit="C", yes_price=0, no_price=0, volume=0,
                    ),
                    direction="NO",
                    edge=abs(gap),
                    reasoning=f"ΣYES={event.sum_yes:.3f}, gap={gap:.3f} (<-{gap_min:.2f}): overpriced, sell/NO side",
                ))

        return recs


class LadderStrategy(Strategy):
    name = "ladder"

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        defaults = self.get_defaults()
        edge_min = kwargs.get("edge_min", defaults.get("edge_min", 0.08))
        spread = kwargs.get("spread", defaults.get("spread", 1.0))
        forecast: ForecastResult | None = kwargs.get("forecast")
        recs: list[Recommendation] = []

        if not forecast:
            return recs

        from pm_bot.core.weather import bucket_probability_numpy
        forecast_center = forecast.mean

        nearby = [b for b in event.buckets
                  if abs(b.temp_center_c - forecast_center) <= spread + 0.5]

        for b in nearby:
            model_prob = bucket_probability_numpy(forecast, b.temp_low_c, b.temp_high_c)
            if b.yes_price <= 0:
                continue
            edge = model_prob - b.yes_price
            if edge >= edge_min:
                recs.append(Recommendation(
                    strategy=self.name,
                    event=event,
                    bucket=b,
                    direction="YES",
                    edge=edge,
                    reasoning=f"forecast_center={forecast_center:.1f}°C, model_prob={model_prob:.2f}, market={b.yes_price:.2f}, edge={edge:.2f}",
                ))
            no_edge = (1 - model_prob) - b.no_price
            if b.no_price > 0 and no_edge >= edge_min:
                recs.append(Recommendation(
                    strategy=self.name,
                    event=event,
                    bucket=b,
                    direction="NO",
                    edge=no_edge,
                    reasoning=f"forecast_center={forecast_center:.1f}°C, model_prob={model_prob:.2f}, NO edge={no_edge:.2f}",
                ))

        return recs


_all_strategies: dict[str, Strategy] | None = None


def get_all_strategies() -> dict[str, Strategy]:
    """Lazy construction to avoid circular imports with narrow_no/airport_arb."""
    global _all_strategies
    if _all_strategies is None:
        from pm_bot.strategies.narrow_no import NarrowNoStrategy
        from pm_bot.strategies.airport_arb import AirportArbStrategy

        _all_strategies = {
            "gopfan2": Gopfan2Strategy(),
            "sum_arb": SumArbStrategy(),
            "ladder": LadderStrategy(),
            "narrow_no": NarrowNoStrategy(),
            "airport_arb": AirportArbStrategy(),
        }
    return _all_strategies


# Eager load for backward compatibility — safe because by the time
# external code imports this module, narrow_no/airport_arb are already
# importable (they only need Strategy, which is defined above).
ALL_STRATEGIES: dict[str, Strategy] = get_all_strategies()
