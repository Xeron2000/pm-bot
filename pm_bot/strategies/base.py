from __future__ import annotations

from pm_bot.models.market import Recommendation, WeatherEvent, ForecastResult


class Strategy:
    name: str = "base"

    @property
    def supports_backtest(self) -> bool:
        return True

    def get_defaults(self) -> dict[str, float]:
        from pm_bot.models.config import STRATEGY_DEFAULTS

        return STRATEGY_DEFAULTS.get(self.name, {})

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        return []


class Gopfan2Strategy(Strategy):
    """Buy cheap YES on tail buckets (extreme temperature lottery tickets).

    Only trades tail buckets where mid price <= yes_max (default $0.15).
    These are extreme temperature outcomes that the market thinks are unlikely.
    At $0.01/share, risk/reward is 1:99 (lose $0.01 or win $0.99).

    Mid-bucket trades (mid $0.15-$0.85) are excluded because Polymarket's
    orderbook structure (bid=$0.01/ask=$0.99) makes them negative EV.

    Removed strategies (2026-05-07):
    - neg_risk_field_fade: core is tail-NO, live fill rate <1%
    - neg_risk_sum: core is tail-NO, live fill rate <1%
    - truncation_edge: mid-bucket trades all negative EV
    - ensemble_spread: total P&L was negative
    - resolution_div: mid-bucket trades all negative EV
    """

    name = "gopfan2"

    # Maximum mid price to consider (tail buckets only)
    MAX_TAIL_PRICE = 0.15

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        defaults = self.get_defaults()
        yes_max = kwargs.get("yes_max", defaults.get("yes_max", self.MAX_TAIL_PRICE))
        forecast: ForecastResult | None = kwargs.get("forecast")
        recs: list[Recommendation] = []

        from pm_bot.core.weather import bucket_probability_numpy

        for b in event.buckets:
            if b.yes_price <= 0 or b.yes_price > yes_max:
                continue

            model_prob = (
                bucket_probability_numpy(forecast, b.temp_low_c, b.temp_high_c, b.temp_unit) if forecast else None
            )

            # Only buy YES on tail buckets where model says probability > price
            if model_prob is not None:
                if model_prob > b.yes_price + 0.02:
                    edge = model_prob - b.yes_price
                else:
                    edge = 0.0
            else:
                edge = 0.0

            if edge > 0:
                recs.append(
                    Recommendation(
                        strategy=self.name,
                        event=event,
                        bucket=b,
                        direction="YES",
                        edge=edge,
                        reasoning=f"YES@{b.yes_price:.2f} \u2264 {yes_max:.2f}"
                        + (f", model={model_prob:.2f}" if model_prob else ""),
                    )
                )

        return recs


_all_strategies: dict[str, Strategy] | None = None


def get_all_strategies() -> dict[str, Strategy]:
    """Only gopfan2 (tail-YES lottery) is retained.

    All other strategies removed because:
    - neg_risk_field_fade: core is tail-NO, live fill rate <1%
    - neg_risk_sum: core is tail-NO, live fill rate <1%
    - truncation_edge: mid-bucket trades are all negative EV
    - ensemble_spread: total P&L was negative
    - resolution_div: mid-bucket trades are all negative EV
    """
    global _all_strategies
    if _all_strategies is None:
        _all_strategies = {
            "gopfan2": Gopfan2Strategy(),
        }
    return _all_strategies


# Eager load for backward compatibility
ALL_STRATEGIES: dict[str, Strategy] = get_all_strategies()
