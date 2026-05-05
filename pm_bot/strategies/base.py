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
    name = "gopfan2"

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        defaults = self.get_defaults()
        yes_max = kwargs.get("yes_max", defaults.get("yes_max", 0.15))
        no_min = kwargs.get("no_min", defaults.get("no_min", 0.45))
        forecast: ForecastResult | None = kwargs.get("forecast")
        recs: list[Recommendation] = []

        from pm_bot.core.weather import bucket_probability_numpy

        for b in event.buckets:
            if b.yes_price <= 0 or b.no_price <= 0:
                continue

            model_prob = (
                bucket_probability_numpy(forecast, b.temp_low_c, b.temp_high_c, b.temp_unit) if forecast else None
            )

            if b.yes_price <= yes_max:
                if model_prob is not None:
                    if model_prob > b.yes_price + 0.05:
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
                            reasoning=f"YES@{b.yes_price:.2f} ≤ {yes_max:.2f}"
                            + (f", model={model_prob:.2f}" if model_prob else ""),
                        )
                    )

            elif b.no_price >= no_min:
                if model_prob is not None:
                    if (1.0 - model_prob) > b.no_price + 0.05:
                        edge = (1.0 - model_prob) - b.no_price
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
                            direction="NO",
                            edge=edge,
                            reasoning=f"NO@{b.no_price:.2f} ≥ {no_min:.2f}"
                            + (f", model={1 - model_prob:.2f}" if model_prob else ""),
                        )
                    )

        return recs


_all_strategies: dict[str, Strategy] | None = None


def get_all_strategies() -> dict[str, Strategy]:
    """Lazy construction to avoid circular imports."""
    global _all_strategies
    if _all_strategies is None:
        from pm_bot.strategies.resolution_divergence import ResolutionDivergenceStrategy
        from pm_bot.strategies.neg_risk_sum import NegRiskSumStrategy
        from pm_bot.strategies.truncation_edge import TruncationEdgeStrategy
        from pm_bot.strategies.ensemble_spread import EnsembleSpreadStrategy
        from pm_bot.strategies.neg_risk_field_fade import NegRiskFieldFadeStrategy

        _all_strategies = {
            "gopfan2": Gopfan2Strategy(),
            "resolution_div": ResolutionDivergenceStrategy(),
            "neg_risk_sum": NegRiskSumStrategy(),
            "truncation_edge": TruncationEdgeStrategy(),
            "ensemble_spread": EnsembleSpreadStrategy(),
            "neg_risk_field_fade": NegRiskFieldFadeStrategy(),
        }
    return _all_strategies


# Eager load for backward compatibility
ALL_STRATEGIES: dict[str, Strategy] = get_all_strategies()
