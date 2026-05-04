from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
import structlog

from pm_bot.backtest.costs import CostModel
from pm_bot.backtest.data import HistoricalDataFetcher
from pm_bot.backtest.metrics import calculate_metrics
from pm_bot.core.kelly import kelly_size
from pm_bot.models.market import ForecastResult, TemperatureBucket, WeatherEvent

log = structlog.get_logger()


@dataclass
class SimulatedTrade:
    date: str
    strategy: str
    bucket_key: str
    direction: str
    price: float
    size_usd: float
    cost: float
    pnl: float = 0.0
    resolved: bool = False


@dataclass
class BacktestResult:
    strategy_name: str
    bankroll: float
    final_value: float
    total_pnl: float
    trades: list[SimulatedTrade] = field(default_factory=list)
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    brier_score: float = 0.0


class BacktestEngine:
    def __init__(
        self,
        strategies: list,
        bankroll: float = 100.0,
        days: int = 90,
        costs: CostModel | None = None,
        cities: list[str] | None = None,
    ) -> None:
        self.strategies = strategies
        self.bankroll = bankroll
        self.days = days
        self.costs = costs or CostModel()
        self.cities = cities or ["NYC"]

    async def run(self) -> list[BacktestResult]:
        fetcher = HistoricalDataFetcher()
        results: list[BacktestResult] = []

        today = datetime.now(timezone.utc).date()

        async with httpx.AsyncClient(timeout=30.0) as client:
            for strat in self.strategies:
                trades: list[SimulatedTrade] = []
                bankroll_series: list[float] = [self.bankroll]
                current_bankroll = self.bankroll

                for day_offset in range(self.days):
                    run_date = today - timedelta(days=self.days - day_offset)
                    date_str = run_date.isoformat()

                    for city in self.cities:
                        forecast = await fetcher.fetch_historical_forecasts(client, city, date_str)
                        obs_temp = await fetcher.fetch_historical_observations(client, city, date_str)

                        if not forecast:
                            continue

                        event = self._build_synthetic_event(city, date_str, forecast)
                        kwargs: dict = {"forecast": forecast, "bankroll": current_bankroll}

                        recs = strat.run(event, **kwargs)

                        for rec in recs:
                            size = kelly_size(
                                edge=rec.edge,
                                yes_price=rec.bucket.yes_price,
                                bankroll=current_bankroll,
                                kelly_fraction_val=0.25,
                                max_single=current_bankroll * 0.1,
                            )
                            if size < 0.5:
                                continue

                            cost = self.costs.calculate_cost("taker", rec.price, size)
                            resolved = obs_temp is not None
                            pnl = 0.0

                            if resolved and obs_temp is not None:
                                hit = self._bucket_hit(rec.bucket, obs_temp)
                                if rec.direction == "YES":
                                    pnl = size * (1.0 - rec.price) - cost if hit else -size * rec.price - cost
                                else:
                                    pnl = size * rec.price - cost if not hit else -size * (1.0 - rec.price) - cost

                            trade = SimulatedTrade(
                                date=date_str,
                                strategy=strat.name,
                                bucket_key=f"{rec.bucket.temp_low_c}-{rec.bucket.temp_high_c}",
                                direction=rec.direction,
                                price=rec.price,
                                size_usd=size,
                                cost=cost,
                                pnl=pnl,
                                resolved=resolved,
                            )
                            trades.append(trade)

                            if resolved:
                                current_bankroll += pnl
                                current_bankroll = max(current_bankroll, 0.01)

                    bankroll_series.append(current_bankroll)

                metrics = calculate_metrics(trades, bankroll_series)

                results.append(BacktestResult(
                    strategy_name=strat.name,
                    bankroll=self.bankroll,
                    final_value=current_bankroll,
                    total_pnl=current_bankroll - self.bankroll,
                    trades=trades,
                    sharpe_ratio=metrics.get("sharpe", 0.0),
                    sortino_ratio=metrics.get("sortino", 0.0),
                    max_drawdown=metrics.get("max_drawdown", 0.0),
                    win_rate=metrics.get("win_rate", 0.0),
                    avg_win=metrics.get("avg_win", 0.0),
                    avg_loss=metrics.get("avg_loss", 0.0),
                    brier_score=metrics.get("brier_score", 0.0),
                ))

        fetcher.close()
        return results

    def _build_synthetic_event(
        self,
        city: str,
        date: str,
        forecast: ForecastResult,
    ) -> WeatherEvent:
        mean = forecast.mean
        buckets: list[TemperatureBucket] = []
        for i in range(-4, 5):
            low = mean + (i * 2.0) - 1.0
            high = mean + (i * 2.0) + 1.0
            from pm_bot.core.weather import bucket_probability_numpy
            prob = bucket_probability_numpy(forecast, low, high)
            buckets.append(TemperatureBucket(
                market_id=f"synth_{city}_{date}_{i}",
                question=f"Temp {low:.0f}-{high:.0f}°C",
                temp_low=low,
                temp_high=high,
                temp_unit="C",
                yes_price=prob,
                no_price=1.0 - prob,
                volume=0.0,
            ))

        return WeatherEvent(
            event_id=f"synth_{city}_{date}",
            title=f"High temp in {city} on {date}",
            slug=f"{city}-{date}",
            city=city,
            date=date,
            buckets=buckets,
        )

    def _bucket_hit(self, bucket: TemperatureBucket, obs_c: float) -> bool:
        if bucket.is_low_tail:
            return obs_c <= bucket.temp_high_c
        if bucket.is_high_tail:
            return obs_c >= bucket.temp_low_c
        return bucket.temp_low_c <= obs_c <= bucket.temp_high_c

