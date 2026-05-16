"""EMOS-enhanced forecast arbitrage strategy.

Uses calibrated probabilities instead of raw ensemble counts.
More accurate edge calculation leads to better trade selection.
"""

from __future__ import annotations

from pm_bot.core.emos import EMOSCalibrator, bucket_probability_emos
from pm_bot.models.market import ForecastResult, Recommendation, WeatherEvent
from pm_bot.strategies.base import Strategy


class EMOSForecastArbStrategy(Strategy):
    """EMOS-enhanced forecast arbitrage strategy.

    Uses calibrated probabilities instead of raw ensemble counts.
    More accurate edge calculation leads to better trade selection.
    """

    name = "emos_forecast_arb"

    def __init__(
        self,
        edge_threshold: float = 0.15,
        bankroll: float = 1000.0,
        kelly_fraction: float = 0.25,
        max_single_pct: float = 0.02,
        min_notional: float = 1.0,
        max_position_usd: float = 2.0,
        min_mispricing: float = 0.15,
        max_market_price: float = 0.30,
        min_model_prob: float = 0.05,
        emos_calibrator: EMOSCalibrator | None = None,
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
        self.min_mispricing = min_mispricing
        self.max_market_price = max_market_price
        self.min_model_prob = min_model_prob
        self.emos_calibrator = emos_calibrator

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        """Run EMOS-enhanced forecast arbitrage strategy."""
        forecast: ForecastResult | None = kwargs.get("forecast")
        bankroll = kwargs.get("bankroll", self.bankroll)
        calibrator = kwargs.get("emos_calibrator", self.emos_calibrator)

        if not forecast or not forecast.members:
            return []

        recs: list[Recommendation] = []

        for b in event.buckets:
            # Calculate calibrated probability
            if calibrator and calibrator._trained:
                model_prob = bucket_probability_emos(
                    calibrator,
                    forecast.members,
                    b.temp_low_c,
                    b.temp_high_c,
                    b.temp_unit,
                )
            else:
                from pm_bot.core.weather import bucket_probability_numpy

                model_prob = bucket_probability_numpy(
                    forecast,
                    b.temp_low_c,
                    b.temp_high_c,
                    b.temp_unit,
                )

            if model_prob < self.min_model_prob:
                continue

            market_price = b.yes_price
            if market_price <= 0:
                continue

            mispricing = model_prob - market_price

            # BUY YES when model >> market
            if mispricing >= self.min_mispricing and market_price <= self.max_market_price:
                # Kelly sizing
                win_payout = 1.0 - market_price
                loss_amt = market_price
                raw_kelly = (model_prob * win_payout - (1 - model_prob) * loss_amt) / win_payout

                if raw_kelly <= 0:
                    continue

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
                        edge=mispricing,
                        reasoning=(
                            f"EMOS-ARB {b.temp_low_c}-{b.temp_high_c}C "
                            f"(model={model_prob:.1%} vs market={market_price:.1%})"
                        ),
                        size_usd=position_usd,
                        kelly_fraction=raw_kelly,
                    )
                )

        recs.sort(key=lambda r: r.edge, reverse=True)
        return recs[:3]
