from __future__ import annotations

from pm_bot.models.market import Recommendation, WeatherEvent, ForecastResult


class Strategy:
    """Base strategy for Polymarket weather trading.

    Principles:
    - Quarter Kelly (kelly_fraction=0.25) for safety
    - 8% minimum edge threshold for weather trades
    - Max 2% of bankroll per trade
    - Keep 30% cash reserve (max_total_pct=0.70)
    """

    name: str = "base"

    def __init__(
        self,
        edge_threshold: float = 0.08,
        bankroll: float = 1000.0,
        kelly_fraction: float = 0.25,
        max_single_pct: float = 0.02,
        min_notional: float = 1.0,
        max_position_usd: float = 2.0,
        **kwargs,
    ):
        self.edge_threshold = edge_threshold
        self.bankroll = bankroll
        self.kelly_fraction = kelly_fraction
        self.max_single_pct = max_single_pct
        self.min_notional = min_notional
        self.max_position_usd = max_position_usd

    @property
    def supports_backtest(self) -> bool:
        return True

    def get_defaults(self) -> dict[str, float]:
        from pm_bot.models.config import STRATEGY_DEFAULTS

        return STRATEGY_DEFAULTS.get(self.name, {})

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        return []


_all_strategies: dict[str, Strategy] | None = None


def get_all_strategies() -> dict[str, Strategy]:
    """All active strategies for Polymarket temperature markets.

    Core strategies:
    - forecast_arb: model vs market mispricing exploit
    - emos_forecast_arb: EMOS-enhanced forecast arb (calibrated probabilities)
    - barbell: tail buys + high-conviction central bets (ColdMath style)
    - adaptive_barbell: barbell with dynamic ratio adjustment
    """
    global _all_strategies
    if _all_strategies is None:
        from pm_bot.strategies.forecast_arb import ForecastArbStrategy
        from pm_bot.strategies.emos_strategies import EMOSForecastArbStrategy
        from pm_bot.strategies.barbell import BarbellStrategy, AdaptiveBarbellStrategy
        from pm_bot.models.config import STRATEGY_DEFAULTS

        _all_strategies = {
            "forecast_arb": ForecastArbStrategy(**STRATEGY_DEFAULTS.get("forecast_arb", {})),
            "emos_forecast_arb": EMOSForecastArbStrategy(**STRATEGY_DEFAULTS.get("emos_forecast_arb", {})),
            "barbell": BarbellStrategy(**STRATEGY_DEFAULTS.get("barbell", {})),
            "adaptive_barbell": AdaptiveBarbellStrategy(**STRATEGY_DEFAULTS.get("adaptive_barbell", {})),
        }
    return _all_strategies


ALL_STRATEGIES: dict[str, Strategy] = get_all_strategies()
