from __future__ import annotations

from pm_bot.models.market import Recommendation, WeatherEvent, ForecastResult


class Strategy:
    """Base strategy for small-capital Polymarket trading.

    Designed for $500-$2000 bankrolls using gopfan2-style micro-positions.
    Key principles (from industry research):
    - 2% rule: max 2% of bankroll per trade ($10-$40 on $500-$2000)
    - Quarter Kelly: kelly_fraction=0.25 for safety
    - 8% minimum edge threshold for weather trades
    - Keep 30% cash reserve (max_total_pct=0.70)
    - $1-$2 per position for tail trades (gopfan2 proven approach)
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


class Gopfan2Strategy(Strategy):
    """Buy cheap YES on tail buckets — small-capital optimized.

    Proven strategy: gopfan2 earned $343K+ with $1-$2 per position.
    Only trades tail buckets where mid price <= $0.15.
    Edge threshold raised to 8% (industry standard for weather trades).

    Small-capital rules:
    - Max $2 per position (diversification across many small bets)
    - Quarter Kelly (0.25) for safety
    - 8% minimum edge (not 2% — too many noise trades at 2%)
    - Cap total exposure at 70% of bankroll
    """

    name = "gopfan2"

    MAX_TAIL_PRICE = 0.15

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
        super().__init__(
            edge_threshold=edge_threshold,
            bankroll=bankroll,
            kelly_fraction=kelly_fraction,
            max_single_pct=max_single_pct,
            min_notional=min_notional,
            max_position_usd=max_position_usd,
            **kwargs,
        )

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        defaults = self.get_defaults()
        yes_max = kwargs.get("yes_max", defaults.get("yes_max", self.MAX_TAIL_PRICE))
        forecast: ForecastResult | None = kwargs.get("forecast")
        bankroll = kwargs.get("bankroll", self.bankroll)
        recs: list[Recommendation] = []

        from pm_bot.core.weather import bucket_probability_numpy

        for b in event.buckets:
            if b.yes_price <= 0 or b.yes_price > yes_max:
                continue

            model_prob = (
                bucket_probability_numpy(forecast, b.temp_low_c, b.temp_high_c, b.temp_unit) if forecast else None
            )

            # Require model validation — don't blind-buy
            if model_prob is not None:
                edge = model_prob - b.yes_price
                if edge < self.edge_threshold:
                    edge = 0.0
            else:
                edge = 0.0

            if edge > 0:
                # Small-capital sizing: $1-$2 per position, quarter Kelly
                win_payout = 1.0 - b.yes_price
                loss_amt = b.yes_price
                raw_kelly = (model_prob * win_payout - (1 - model_prob) * loss_amt) / win_payout

                if raw_kelly <= 0:
                    continue

                # Quarter Kelly, capped at $2 per position
                kelly_per_trade = raw_kelly * self.kelly_fraction
                position_usd = bankroll * kelly_per_trade
                position_usd = min(position_usd, self.max_position_usd)
                position_usd = max(position_usd, self.min_notional)

                recs.append(
                    Recommendation(
                        strategy=self.name,
                        event=event,
                        bucket=b,
                        direction="YES",
                        edge=edge,
                        reasoning=f"YES@{b.yes_price:.2f} \u2264 {yes_max:.2f}"
                        + (f", model={model_prob:.2f}, edge={edge:.1%}" if model_prob else ""),
                        size_usd=position_usd,
                        kelly_fraction=raw_kelly,
                    )
                )

        return recs


_all_strategies: dict[str, Strategy] | None = None


def get_all_strategies() -> dict[str, Strategy]:
    """All active strategies for Polymarket temperature markets.

    Core strategies:
    - gopfan2: tail-YES lottery tickets (mid <= $0.15)
    - forecast_arb: model vs market mispricing exploit
    - emos_gopfan2: EMOS-enhanced gopfan2 (model-validated tails)
    - emos_forecast_arb: EMOS-enhanced forecast arb (calibrated probabilities)
    """
    global _all_strategies
    if _all_strategies is None:
        from pm_bot.strategies.forecast_arb import ForecastArbStrategy
        from pm_bot.strategies.emos_strategies import EMOSGopfan2Strategy, EMOSForecastArbStrategy
        from pm_bot.models.config import STRATEGY_DEFAULTS

        _all_strategies = {
            "gopfan2": Gopfan2Strategy(**STRATEGY_DEFAULTS.get("gopfan2", {})),
            "forecast_arb": ForecastArbStrategy(**STRATEGY_DEFAULTS.get("forecast_arb", {})),
            "emos_gopfan2": EMOSGopfan2Strategy(**STRATEGY_DEFAULTS.get("emos_gopfan2", {})),
            "emos_forecast_arb": EMOSForecastArbStrategy(**STRATEGY_DEFAULTS.get("emos_forecast_arb", {})),
        }
    return _all_strategies


ALL_STRATEGIES: dict[str, Strategy] = get_all_strategies()
