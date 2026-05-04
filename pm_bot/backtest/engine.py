from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
import structlog

from pm_bot.backtest.costs import CostModel
from pm_bot.backtest.data import HistoricalDataFetcher
from pm_bot.backtest.metrics import calculate_metrics
from pm_bot.backtest.real_data import RealDataFetcher, ResolvedEvent
from pm_bot.core.kelly import kelly_size
from pm_bot.core.parser import parse_bucket
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

    async def run_real(self) -> list[BacktestResult]:
        """Run backtest using real Polymarket resolved events + CLOB prices.

        Fetches resolved events via series_slug, enriches with CLOB T-24h
        prices, then runs strategies against actual market prices.
        P&L is computed against the actual resolution.
        """
        fetcher = RealDataFetcher()
        results: list[BacktestResult] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            resolved_events = await fetcher.fetch_resolved_weather_events(client, days=self.days)
            if not resolved_events:
                log.warning("no_resolved_events_found", days=self.days)
                fetcher.close()
                return []

            log.info("resolved_events_count", count=len(resolved_events))

            await fetcher.enrich_events_with_clob_prices(client, resolved_events)

            unique_cities = list({ev.city for ev in resolved_events})
            await fetcher.prefetch_forecasts(client, unique_cities, self.days)

            for strat in self.strategies:
                trades: list[SimulatedTrade] = []
                bankroll_series: list[float] = [self.bankroll]
                current_bankroll = self.bankroll

                for ev in resolved_events:
                    forecast = fetcher.get_cached_forecast(ev.city, ev.target_date, ev.measure_type)
                    if forecast is None:
                        log.debug("no_forecast_for_event", city=ev.city, date=ev.target_date)
                        continue

                    event = self._build_real_event_from_resolution(ev, forecast)
                    if event is None:
                        continue

                    kwargs: dict = {"forecast": forecast, "bankroll": current_bankroll}
                    recs = strat.run(event, **kwargs)

                    for rec in recs:
                        effective_price = rec.price

                        size = kelly_size(
                            edge=rec.edge,
                            yes_price=rec.bucket.yes_price,
                            bankroll=current_bankroll,
                            kelly_fraction_val=0.25,
                            max_single=current_bankroll * 0.1,
                        )
                        if size < 0.5:
                            continue

                        cost = self.costs.calculate_cost("taker", effective_price, size)

                        hit = self._real_bucket_hit(ev, rec.bucket)

                        if rec.direction == "YES":
                            pnl = size * (1.0 - effective_price) - cost if hit else -size * effective_price - cost
                        else:
                            pnl = size * (1.0 - effective_price) - cost if not hit else -size * effective_price - cost

                        trade = SimulatedTrade(
                            date=ev.target_date,
                            strategy=strat.name,
                            bucket_key=f"{rec.bucket.temp_low_c:.0f}-{rec.bucket.temp_high_c:.0f}",
                            direction=rec.direction,
                            price=effective_price,
                            size_usd=size,
                            cost=cost,
                            pnl=pnl,
                            resolved=True,
                        )
                        trades.append(trade)

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

    def _build_real_event_from_resolution(
        self,
        ev: ResolvedEvent,
        forecast: ForecastResult,
    ) -> WeatherEvent | None:
        """Build a WeatherEvent for real-data backtesting.

        Uses CLOB T-24h prices where available (enriched by
        enrich_events_with_clob_prices). Falls back to forecast-derived
        probability for markets without CLOB data.
        """
        from pm_bot.core.weather import bucket_probability_numpy

        buckets: list[TemperatureBucket] = []
        for m in ev.markets:
            bucket = parse_bucket(m.question, m.token_id, yes_price=0.0, no_price=1.0, volume=0.0)
            if bucket is not None:
                if m.yes_price > 0.01 and m.yes_price < 0.99:
                    bucket.yes_price = m.yes_price
                    bucket.no_price = m.no_price
                else:
                    prob = bucket_probability_numpy(forecast, bucket.temp_low_c, bucket.temp_high_c)
                    bucket.yes_price = prob
                    bucket.no_price = 1.0 - prob
                buckets.append(bucket)

        if not buckets:
            return None

        def sort_key(b: TemperatureBucket) -> float:
            if b.is_low_tail:
                return float("-inf")
            return b.temp_low_c

        buckets.sort(key=sort_key)

        return WeatherEvent(
            event_id=ev.event_id,
            title=ev.title,
            slug=ev.slug,
            city=ev.city,
            date=ev.target_date,
            measure_type=ev.measure_type,
            buckets=buckets,
        )

    def _real_bucket_hit(self, ev: ResolvedEvent, bucket: TemperatureBucket) -> bool:
        """Check if a bucket was the winning one in a resolved event."""
        for m in ev.markets:
            if m.token_id == bucket.market_id:
                return m.winning
        return False

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
