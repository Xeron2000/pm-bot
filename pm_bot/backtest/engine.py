from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
import structlog

from pm_bot.backtest.costs import CostModel, FillModel
from pm_bot.backtest.data import HistoricalDataFetcher
from pm_bot.backtest.metrics import calculate_metrics
from pm_bot.backtest.real_data import RealDataFetcher, ResolvedEvent
from pm_bot.core.kelly import kelly_size
from pm_bot.core.parser import parse_bucket
from pm_bot.models.market import ForecastResult, Recommendation, TemperatureBucket, WeatherEvent

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
    entry_price: float = 0.0
    stop_loss_pct: float = 0.0
    price_source: str = "clob"
    filled: bool = True


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
        stop_loss_pct: float = 0.0,
        kelly_fraction_val: float = 0.25,
        max_single_pct: float = 0.10,
        max_notional: float = 100.0,
        compound: bool = True,
        live_mode: bool = False,
        seed: int | None = None,
        fill_model: FillModel | None = None,
        preloaded_fetcher: RealDataFetcher | None = None,
        preloaded_events: list | None = None,
        spread_pct: float = 0.0,
        synthetic_only: bool = False,
    ) -> None:
        self.strategies = strategies
        self.bankroll = bankroll
        self.days = days
        self.costs = costs or CostModel()
        self.cities = cities or ["NYC"]
        self.stop_loss_pct = stop_loss_pct
        self.kelly_fraction_val = kelly_fraction_val
        self.max_single_pct = max_single_pct
        self.max_notional = max_notional
        self.compound = compound
        self.live_mode = live_mode
        self.seed = seed
        self.spread_pct = spread_pct
        self.synthetic_only = synthetic_only
        self._preloaded_fetcher = preloaded_fetcher
        self._preloaded_events = preloaded_events
        if fill_model is not None:
            self.costs.fill_model = fill_model
        if live_mode:
            self.costs.live_mode = True
        self._rng = random.Random(seed)

    async def run(self) -> list[BacktestResult]:
        fetcher = HistoricalDataFetcher()
        results: list[BacktestResult] = []

        today = datetime.now(timezone.utc).date()

        async with httpx.AsyncClient(timeout=30.0) as client:
            for strat in self.strategies:
                trades: list[SimulatedTrade] = []
                bankroll_series: list[float] = [self.bankroll]
                current_bankroll = self.bankroll
                cumulative_pnl = 0.0

                for day_offset in range(self.days):
                    run_date = today - timedelta(days=self.days - day_offset)
                    date_str = run_date.isoformat()
                    date_str = run_date.isoformat()

                    for city in self.cities:
                        if self.synthetic_only:
                            # Generate synthetic ForecastResult with realistic spread
                            import random as _rng
                            _seed = hash(f"{city}{date_str}") % 2**32
                            _r = _rng.Random(_seed)
                            temp_high = 20 + _r.uniform(-5, 15)  # Random temp 15-35C
                            # Create ForecastResult with 200 ensemble members for good probability estimation
                            from pm_bot.models.market import ForecastResult
                            forecast = ForecastResult(
                                city=city,
                                date=date_str,
                                model="synthetic",
                                temp_high_c=temp_high,
                                members=[temp_high + _r.gauss(0, 3.0) for _ in range(200)],
                            )
                            obs_temp = temp_high + _r.gauss(0, 1)  # Slightly different observation
                        else:
                            forecast = await fetcher.fetch_historical_forecasts(client, city, date_str)
                            obs_temp = await fetcher.fetch_historical_observations(client, city, date_str)

                        if not forecast:
                            continue

                        event = self._build_synthetic_event(city, date_str, forecast)
                        kwargs: dict = {"forecast": forecast, "bankroll": current_bankroll}

                        if obs_temp is not None:
                            from pm_bot.core.observation import ObservedTemp

                            obs_obj = ObservedTemp(
                                city=city,
                                observed_c=obs_temp,
                                obs_time_utc=datetime.now(timezone.utc),
                                local_time=datetime.now(timezone.utc),
                                is_past_cutoff=True,
                            )
                            kwargs["observation"] = obs_obj

                        recs = strat.run(event, **kwargs)

                        for rec in recs:
                            effective_price = rec.price
                            side = self.costs.live_side if self.live_mode else "taker"

                            size = self._compute_position_size(rec, current_bankroll, effective_price)
                            if size is None:
                                continue
                            if size * rec.bucket.yes_price < 0.5:
                                continue

                            hit = self._bucket_hit(rec.bucket, obs_temp) if obs_temp is not None else None
                            resolved = obs_temp is not None

                            trade = self._resolve_trade(
                                rec=rec,
                                effective_price=effective_price,
                                side=side,
                                size=size,
                                source="clob",
                                hit=hit,
                                resolved=resolved,
                                date_str=date_str,
                                strategy_name=strat.name,
                            )
                            trades.append(trade)

                            if trade.resolved:
                                current_bankroll += trade.pnl
                                current_bankroll = max(current_bankroll, 0.01)
                                cumulative_pnl += trade.pnl
                                if not self.compound:
                                    current_bankroll = self.bankroll

                    self._append_bankroll_series(bankroll_series, current_bankroll, cumulative_pnl)

                metrics = calculate_metrics(trades, bankroll_series)
                results.append(self._build_result(strat.name, cumulative_pnl, current_bankroll, trades, metrics))

        return results

    async def _get_events_and_fetcher(self):
        """Fetch events or use preloaded data. Returns (fetcher, all_events, client_or_none)."""
        if self._preloaded_events is not None and self._preloaded_fetcher is not None:
            fetcher = self._preloaded_fetcher
            all_events = self._preloaded_events
            if self.cities:
                from pm_bot.models.config import resolve_city_alias

                allowed = {resolve_city_alias(c) for c in self.cities}
                all_events = [ev for ev in all_events if ev.city in allowed]
            return fetcher, all_events, None

        fetcher = RealDataFetcher()
        client = httpx.AsyncClient(timeout=30.0)
        return fetcher, None, client

    def _apply_spread(self, price: float, direction: str = "YES") -> float:
        """Apply realistic Polymarket orderbook spread.

        Polymarket weather markets have a structural orderbook:
        - YES bid = $0.010, YES ask = $0.990
        - NO  bid = $0.010, NO  ask = $0.990
        - Mid price is calculated as (bid + ask) / 2 = $0.500

        For extreme prices (tail buckets), the orderbook is:
        - YES mid $0.01-$0.15: buy YES at ask=$0.990 (useless), buy NO at bid=$0.010 (if you want to short)
        - YES mid $0.85+: buy YES at bid=$0.010 (if you want to go long), buy NO at ask=$0.990 (useless)

        In practice, only tail buckets (mid < $0.15 or mid > $0.85) have any edge.
        For those, the effective fill price is $0.01 (bid side) — you place a limit order at $0.01
        and wait for someone to market-sell into it.

        Args:
            price: Mid price from the orderbook
            direction: "YES" or "NO"
        Returns:
            Effective entry price after spread
        """
        if self.spread_pct <= 0:
            return price

        # spread_pct acts as the orderbook ask price for non-tail buckets
        # For tail buckets (where real edge lives), use $0.01 bid
        if price <= 0.15 or price >= 0.85:
            # Tail bucket: place limit order at $0.01, hope for fill
            return 0.01
        else:
            # Mid bucket: buy at ask (spread_pct as ask price)
            return min(self.spread_pct, 0.99)

    def _compute_position_size(
        self,
        rec: Recommendation,
        current_bankroll: float,
        effective_price: float,
    ) -> float | None:
        """Compute Kelly-capped position size. Returns None if trade should be skipped."""
        if self.live_mode and rec.edge < self.costs.live_min_edge:
            return None

        size = kelly_size(
            edge=rec.edge,
            yes_price=effective_price,
            bankroll=current_bankroll,
            kelly_fraction_val=self.kelly_fraction_val,
            max_single=current_bankroll * self.max_single_pct,
        )
        size = min(size, self.max_notional)
        if self.live_mode:
            size = min(size, self.costs.live_max_position_usd / max(effective_price, 0.01))
        if self.live_mode and not self.costs.passes_live_filter(rec.edge, size):
            return None
        return size

    def _resolve_trade(
        self,
        rec: Recommendation,
        effective_price: float,
        side: str,
        size: float,
        source: str,
        hit: bool | None,
        resolved: bool,
        date_str: str,
        strategy_name: str,
    ) -> SimulatedTrade:
        """Resolve a single trade: fill model, costs, PnL, stop loss.

        Args:
            rec: Strategy recommendation.
            effective_price: Entry price (with spread applied).
            side: Cost model side ("taker" or "maker").
            size: Position size in contracts.
            source: Price source ("clob", "dune", "forecast", etc.).
            hit: Whether the bucket hit (None if unresolved).
            resolved: Whether the event is settled.
            date_str: Trade date string.
            strategy_name: Strategy name for the trade record.
        """
        # FillModel: Bernoulli trial for maker-side orders in live mode
        filled = True
        if self.live_mode and side == "maker" and self.costs.fill_model is not None:
            fill_prob = self.costs.fill_model.fill_probability(effective_price)
            filled = self._rng.random() < fill_prob

        if not filled:
            return SimulatedTrade(
                date=date_str,
                strategy=strategy_name,
                bucket_key=f"{rec.bucket.temp_low_c:.0f}-{rec.bucket.temp_high_c:.0f}",
                direction=rec.direction,
                price=effective_price,
                size_usd=size,
                cost=0.0,
                pnl=0.0,
                resolved=resolved,
                entry_price=effective_price,
                stop_loss_pct=self.stop_loss_pct,
                price_source=source,
                filled=False,
            )

        cost = self.costs.calculate_cost(side, effective_price, size)
        if source == "forecast":
            cost += self.costs.forecast_penalty_cost(effective_price, size)

        no_price = 1.0 - effective_price

        if not resolved or hit is None:
            pnl = 0.0
        else:
            if rec.direction == "YES":
                raw_pnl = size * (1.0 - effective_price) if hit else -size * effective_price
            else:
                raw_pnl = size * (1.0 - effective_price) if not hit else -size * effective_price

            pnl = raw_pnl - cost

            # Stop loss: cap downside at stop_loss_pct of max investment
            if self.stop_loss_pct > 0 and raw_pnl < 0:
                max_investment = size * (no_price if rec.direction == "NO" else effective_price)
                max_loss = max_investment * self.stop_loss_pct
                if abs(raw_pnl) > max_loss:
                    slippage = self.costs.stop_loss_slippage(max_investment)
                    pnl = -max_loss - cost - slippage

        return SimulatedTrade(
            date=date_str,
            strategy=strategy_name,
            bucket_key=f"{rec.bucket.temp_low_c:.0f}-{rec.bucket.temp_high_c:.0f}",
            direction=rec.direction,
            price=effective_price,
            size_usd=size,
            cost=cost,
            pnl=pnl,
            resolved=resolved,
            entry_price=effective_price,
            stop_loss_pct=self.stop_loss_pct,
            price_source=source,
            filled=True,
        )

    def _append_bankroll_series(
        self,
        bankroll_series: list[float],
        current_bankroll: float,
        cumulative_pnl: float,
    ) -> None:
        """Append one entry to the bankroll series, respecting compound mode."""
        bankroll_series.append(current_bankroll + (cumulative_pnl if not self.compound else 0.0))

    def _build_result(
        self,
        strategy_name: str,
        cumulative_pnl: float,
        current_bankroll: float,
        trades: list[SimulatedTrade],
        metrics: dict[str, float],
    ) -> BacktestResult:
        """Build a BacktestResult from completed trade data."""
        return BacktestResult(
            strategy_name=strategy_name,
            bankroll=self.bankroll,
            final_value=self.bankroll
            + (cumulative_pnl if not self.compound else current_bankroll - self.bankroll),
            total_pnl=cumulative_pnl if not self.compound else current_bankroll - self.bankroll,
            trades=trades,
            sharpe_ratio=metrics.get("sharpe", 0.0),
            sortino_ratio=metrics.get("sortino", 0.0),
            max_drawdown=metrics.get("max_drawdown", 0.0),
            win_rate=metrics.get("win_rate", 0.0),
            avg_win=metrics.get("avg_win", 0.0),
            avg_loss=metrics.get("avg_loss", 0.0),
            brier_score=metrics.get("brier_score", 0.0),
        )

    async def run_real(self) -> list[BacktestResult]:
        """Run backtest using real Polymarket resolved + active events + CLOB prices.

        Fetches resolved events via series_slug, enriches with CLOB T-24h
        prices, then runs strategies against actual market prices.
        Also fetches active (unsettled) events and uses Open-Meteo archive
        actual temperatures to simulate settlement.
        P&L is computed against the actual resolution (or simulated for active).
        """
        fetcher, preloaded_events, client = await self._get_events_and_fetcher()
        results: list[BacktestResult] = []

        async with client or httpx.AsyncClient(timeout=30.0) as client_inner:
            if preloaded_events is not None:
                all_events = preloaded_events
            else:
                resolved_events = await fetcher.fetch_resolved_weather_events(client_inner, days=self.days)
                active_events = await fetcher.fetch_active_weather_events(client_inner, days=self.days)
                all_events = resolved_events + active_events

                if not all_events:
                    log.warning("no_events_found", days=self.days)
                    fetcher.close()
                    return []

                if self.cities:
                    from pm_bot.models.config import resolve_city_alias

                    allowed = {resolve_city_alias(c) for c in self.cities}
                    all_events = [ev for ev in all_events if ev.city in allowed]

                log.info(
                    "events_count",
                    resolved=len(resolved_events),
                    active=len(active_events),
                    total=len(all_events),
                )

                if all_events and all_events[0].markets:
                    sample_m = all_events[0].markets[0]
                    if len(sample_m.token_id) > 20:
                        await fetcher.enrich_events_with_clob_prices(client_inner, all_events)
                        from pm_bot.core.config_loader import load_config

                        config = load_config()
                        dune_key = config.get("dune", {}).get("api_key", "")
                        if dune_key:
                            await fetcher.enrich_events_with_dune_prices(client_inner, all_events, dune_key)

                self._actual_temps: dict[str, float] = {}
                if active_events:
                    actual_temps = await fetcher.fetch_actual_temps(client_inner, active_events)
                    self._actual_temps = actual_temps
                    log.info("actual_temps_loaded", count=len(actual_temps))

                active_prices = await fetcher.fetch_active_market_prices(client_inner)
                self._active_price_cache = active_prices

                unique_cities = list({ev.city for ev in all_events})
                await fetcher.prefetch_forecasts(client_inner, unique_cities, self.days)

            fill_count = 0
            skip_count = 0

            for strat in self.strategies:
                trades: list[SimulatedTrade] = []
                bankroll_series: list[float] = [self.bankroll]
                current_bankroll = self.bankroll
                cumulative_pnl = 0.0

                for ev in all_events:
                    forecast = fetcher.get_cached_forecast(ev.city, ev.target_date)
                    if forecast is None:
                        log.debug("no_forecast_for_event", city=ev.city, date=ev.target_date)
                        continue

                    event, price_sources = self._build_real_event_from_resolution(ev, forecast)
                    if event is None:
                        continue

                    kwargs: dict = {"forecast": forecast, "bankroll": current_bankroll}

                    resolved_temp = self._get_resolved_temp(ev)
                    if resolved_temp is not None:
                        from pm_bot.core.observation import ObservedTemp

                        obs_obj = ObservedTemp(
                            city=ev.city,
                            observed_c=resolved_temp,
                            obs_time_utc=datetime.now(timezone.utc),
                            local_time=datetime.now(timezone.utc),
                            is_past_cutoff=True,
                        )
                        kwargs["observation"] = obs_obj

                    recs = strat.run(event, **kwargs)

                    for rec in recs:
                        effective_price = self._apply_spread(rec.price)
                        side = self.costs.live_side if self.live_mode else "taker"
                        source = price_sources.get(rec.bucket.market_id, "clob")

                        size = self._compute_position_size(rec, current_bankroll, effective_price)
                        if size is None:
                            continue
                        if size * effective_price < 0.5:
                            continue

                        hit = self._real_bucket_hit(ev, rec.bucket)
                        trade = self._resolve_trade(
                            rec=rec,
                            effective_price=effective_price,
                            side=side,
                            size=size,
                            source=source,
                            hit=hit,
                            resolved=True,
                            date_str=ev.target_date,
                            strategy_name=strat.name,
                        )
                        trades.append(trade)

                        if not trade.filled:
                            skip_count += 1
                            continue
                        fill_count += 1

                        current_bankroll += trade.pnl
                        current_bankroll = max(current_bankroll, 0.01)
                        cumulative_pnl += trade.pnl
                        if not self.compound:
                            current_bankroll = self.bankroll

                    self._append_bankroll_series(bankroll_series, current_bankroll, cumulative_pnl)

                metrics = calculate_metrics(trades, bankroll_series)
                results.append(self._build_result(strat.name, cumulative_pnl, current_bankroll, trades, metrics))

        if self.live_mode:
            log.info("fill_model_stats", filled=fill_count, skipped=skip_count)

        if self._preloaded_fetcher is None:
            fetcher.close()
        return results

    async def run_portfolio(self) -> BacktestResult:
        """Run all strategies sharing a single bankroll.

        All strategies generate signals per event; overlapping signals on
        the same bucket are merged (max edge wins). Position sizes are
        capped by shared bankroll. This simulates running all strategies
        simultaneously with one account.
        """
        fetcher, preloaded_events, client = await self._get_events_and_fetcher()

        async with client or httpx.AsyncClient(timeout=30.0) as client_inner:
            if preloaded_events is not None:
                all_events = preloaded_events
            else:
                resolved_events = await fetcher.fetch_resolved_weather_events(client_inner, days=self.days)
                active_events = await fetcher.fetch_active_weather_events(client_inner, days=self.days)
                all_events = resolved_events + active_events

                if not all_events:
                    log.warning("no_events_found", days=self.days)
                    fetcher.close()
                    return BacktestResult(
                        strategy_name="portfolio", bankroll=self.bankroll, final_value=self.bankroll, total_pnl=0.0
                    )

                if self.cities:
                    from pm_bot.models.config import resolve_city_alias

                    allowed = {resolve_city_alias(c) for c in self.cities}
                    all_events = [ev for ev in all_events if ev.city in allowed]

                if all_events and all_events[0].markets:
                    sample_m = all_events[0].markets[0]
                    if len(sample_m.token_id) > 20:
                        await fetcher.enrich_events_with_clob_prices(client_inner, all_events)

                if active_events:
                    actual_temps = await fetcher.fetch_actual_temps(client_inner, active_events)
                    self._actual_temps = actual_temps

                active_prices = await fetcher.fetch_active_market_prices(client_inner)
                self._active_price_cache = active_prices

                unique_cities = list({ev.city for ev in all_events})
                await fetcher.prefetch_forecasts(client_inner, unique_cities, self.days)

            trades: list[SimulatedTrade] = []
            bankroll_series: list[float] = [self.bankroll]
            current_bankroll = self.bankroll
            cumulative_pnl = 0.0
            fill_count = 0
            skip_count = 0

            for ev in all_events:
                forecast = fetcher.get_cached_forecast(ev.city, ev.target_date)
                if forecast is None:
                    continue

                event, price_sources = self._build_real_event_from_resolution(ev, forecast)
                if event is None:
                    continue

                kwargs: dict = {"forecast": forecast, "bankroll": current_bankroll}
                resolved_temp = self._get_resolved_temp(ev)
                if resolved_temp is not None:
                    from pm_bot.core.observation import ObservedTemp

                    obs_obj = ObservedTemp(
                        city=ev.city,
                        observed_c=resolved_temp,
                        obs_time_utc=datetime.now(timezone.utc),
                        local_time=datetime.now(timezone.utc),
                        is_past_cutoff=True,
                    )
                    kwargs["observation"] = obs_obj

                # Merge signals from all strategies on the same event
                # Key: (market_id, direction) — keep highest edge signal per bucket+direction
                best_recs: dict[tuple[str, str], Recommendation] = {}
                rec_strats: dict[tuple[str, str], str] = {}
                for strat in self.strategies:
                    recs = strat.run(event, **kwargs)
                    for rec in recs:
                        effective_price = self._apply_spread(rec.price)
                        if self.live_mode and rec.edge < self.costs.live_min_edge:
                            continue
                        key = (rec.bucket.market_id, rec.direction)
                        if key in best_recs:
                            if rec.edge <= best_recs[key].edge:
                                continue
                        best_recs[key] = rec
                        rec_strats[key] = strat.name

                # Cap total exposure per event to 3x single-pos limit
                total_notional = 0.0
                pending: list[tuple[Recommendation, str, str, float]] = []
                for key, rec in best_recs.items():
                    source = price_sources.get(rec.bucket.market_id, "clob")
                    effective_price = self._apply_spread(rec.price)
                    size = self._compute_position_size(rec, current_bankroll, effective_price)
                    if size is None:
                        continue
                    if size * effective_price < 0.5:
                        continue
                    pending.append((rec, source, rec_strats[key], size))
                    total_notional += size * effective_price

                max_exposure = current_bankroll * self.max_single_pct * 3

                # Execute merged signals
                for rec, source, strat_name, size in pending:
                    effective_price = self._apply_spread(rec.price)
                    side = self.costs.live_side if self.live_mode else "taker"
                    if total_notional > max_exposure and total_notional > 0:
                        size = size * (max_exposure / total_notional)

                    hit = self._real_bucket_hit(ev, rec.bucket)
                    trade = self._resolve_trade(
                        rec=rec,
                        effective_price=effective_price,
                        side=side,
                        size=size,
                        source=source,
                        hit=hit,
                        resolved=True,
                        date_str=ev.target_date,
                        strategy_name=strat_name,
                    )
                    trades.append(trade)

                    if not trade.filled:
                        skip_count += 1
                        continue
                    fill_count += 1

                    current_bankroll += trade.pnl
                    current_bankroll = max(current_bankroll, 0.01)
                    cumulative_pnl += trade.pnl
                    if not self.compound:
                        current_bankroll = self.bankroll

                self._append_bankroll_series(bankroll_series, current_bankroll, cumulative_pnl)

        if self.live_mode:
            log.info("portfolio_fill_stats", filled=fill_count, skipped=skip_count)

        metrics = calculate_metrics(trades, bankroll_series)
        if self._preloaded_fetcher is None:
            fetcher.close()

        return self._build_result("portfolio", cumulative_pnl, current_bankroll, trades, metrics)

    def _build_real_event_from_resolution(
        self,
        ev: ResolvedEvent,
        forecast: ForecastResult,
    ) -> tuple[WeatherEvent | None, dict[str, str]]:
        """Build a WeatherEvent for real-data backtesting.

        Price priority (highest to lowest):
        1. CLOB T-24h price (enriched by enrich_events_with_clob_prices)
        2. Dune hourly price (fetched by fetch_dune_prices)
        3. Gamma active outcomePrices
        4. Forecast-derived probability (fallback, with penalty)

        Resolved markets have outcomePrices=0/1, so those are never used
        directly — we always need an external price source.

        Returns (WeatherEvent | None, {market_id: price_source}) where
        price_source is "clob", "dune", "gamma_active", or "forecast".
        """
        from pm_bot.core.weather import bucket_probability_numpy

        buckets: list[TemperatureBucket] = []
        price_sources: dict[str, str] = {}
        clob_count = 0
        dune_count = 0
        forecast_count = 0

        for m in ev.markets:
            bucket = parse_bucket(m.question, m.token_id, yes_price=0.0, no_price=1.0, volume=0.0)
            if bucket is not None:
                source = "clob"
                if m.yes_price > 0.005 and m.yes_price < 0.995:
                    bucket.yes_price = m.yes_price
                    bucket.no_price = m.no_price
                    # Check if this price came from Dune (stored in price_source field)
                    if getattr(m, "price_source", None) == "dune":
                        source = "dune"
                        dune_count += 1
                    else:
                        clob_count += 1
                else:
                    # Check for cached active Gamma price before falling back to forecast
                    active_price = self._get_active_gamma_price(m.token_id)
                    if active_price is not None and 0.01 <= active_price <= 0.99:
                        bucket.yes_price = active_price
                        bucket.no_price = 1.0 - active_price
                        source = "gamma_active"
                    else:
                        prob = bucket_probability_numpy(
                            forecast, bucket.temp_low_c, bucket.temp_high_c, bucket.temp_unit
                        )
                        bucket.yes_price = prob
                        bucket.no_price = 1.0 - prob
                        source = "forecast"
                        forecast_count += 1

                price_sources[bucket.market_id] = source
                buckets.append(bucket)

        if not buckets:
            return None, {}

        sources_used = {"clob": clob_count, "dune": dune_count, "fc": forecast_count}
        non_zero = {k: v for k, v in sources_used.items() if v > 0}
        if non_zero:
            log.debug("price_sources", evt_id=ev.event_id, **non_zero)

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
        ), price_sources

    def _get_active_gamma_price(self, token_id: str) -> float | None:
        """Get cached active Gamma price for a token. Returns None if not cached."""
        if not hasattr(self, "_active_price_cache"):
            return None
        return float(self._active_price_cache[token_id]) if token_id in self._active_price_cache else None

    def _real_bucket_hit(self, ev: ResolvedEvent, bucket: TemperatureBucket) -> bool:
        """Check if a bucket was the winning one in a resolved event.

        For resolved events, uses the winning market flag.
        For active events, uses actual temperature from Open-Meteo archive
        to determine which bucket floor(observed_temp) falls into.
        """
        for m in ev.markets:
            if m.token_id == bucket.market_id:
                if m.winning:
                    return True
                if "-active" in ev.event_id:
                    actual_key = f"{ev.city}|{ev.target_date}"
                    temps: dict[str, float] = getattr(self, "_actual_temps", {})
                    actual_temp = temps.get(actual_key)
                    if actual_temp is not None:
                        import math

                        if bucket.temp_unit == "F":
                            actual_f = actual_temp * 1.8 + 32
                            floored: int = math.floor(actual_f)
                            if bucket.temp_high_c > bucket.temp_low_c:
                                low_f = bucket.temp_low_c * 1.8 + 32
                                high_f = bucket.temp_high_c * 1.8 + 32
                                return bool(low_f <= floored <= high_f)
                            else:
                                return bool(floored >= bucket.temp_low_c * 1.8 + 32)
                        else:
                            floored_i: int = math.floor(actual_temp)
                            if bucket.temp_high_c > bucket.temp_low_c:
                                return bool(bucket.temp_low_c <= floored_i < bucket.temp_high_c)
                            else:
                                return bool(floored_i >= bucket.temp_low_c)
                return False
        return False

    def _get_resolved_temp(self, ev: ResolvedEvent) -> float | None:
        """Extract resolved temperature from winning market title.

        For resolved events, parses the winning market question.
        For active events, uses actual temperature from Open-Meteo archive.
        """
        if "-active" in ev.event_id:
            actual_key = f"{ev.city}|{ev.target_date}"
            temps: dict[str, float] = getattr(self, "_actual_temps", {})
            actual_temp = temps.get(actual_key)
            if actual_temp is not None:
                return float(actual_temp)
            return None

        for m in ev.markets:
            if not m.winning:
                continue
            q = m.question
            import re

            match = re.search(r"(\d+)(?:\s*[-–]\s*(\d+))?\s*°([CF])", q)
            if match:
                low_str = match.group(1)
                unit = match.group(3)
                low = float(low_str)
                if unit == "F":
                    low = (low - 32) / 1.8
                return low
            match = re.search(r"above\s+(\d+)\s*°([CF])", q, re.IGNORECASE)
            if match:
                val = float(match.group(1))
                if match.group(2) == "F":
                    val = (val - 32) / 1.8
                return val
        return None

    def _build_synthetic_event(
        self,
        city: str,
        date: str,
        forecast: ForecastResult,
    ) -> WeatherEvent:
        mean = forecast.mean
        buckets: list[TemperatureBucket] = []
        # Use integer boundaries for buckets (like real Polymarket markets)
        base = int(mean) - 8  # Start 8 degrees below mean
        for i in range(9):  # 9 buckets
            low = base + (i * 2)
            high = low + 2
            from pm_bot.core.weather import bucket_probability_numpy

            prob = bucket_probability_numpy(forecast, low, high, "C")
            # Add noise to market prices to create realistic edges
            # Market prices are noisy estimates of true probability
            # For tail buckets, market often overprices (higher than true prob)
            # This creates buying opportunities when model says prob > market
            if prob > 0.01:
                # Normal bucket: market price has ±20% relative noise
                noise = self._rng.gauss(0, 0.20) * prob
                market_price = max(0.01, min(0.99, prob + noise))
            else:
                # Very low prob bucket: market often prices at 0.01-0.05
                # even when true prob is near 0
                market_price = self._rng.uniform(0.01, 0.05)
            # For tail buckets (prob < 0.10), add extra noise
            if prob < 0.10 and prob > 0:
                noise_extra = self._rng.gauss(0, 0.03)  # Extra ±3% noise for tails
                market_price = max(0.01, min(0.30, market_price + noise_extra))

            buckets.append(
                TemperatureBucket(
                    market_id=f"synth_{city}_{date}_{i}",
                    question=f"Temp {low}-{high}°C",
                    temp_low=low,
                    temp_high=high,
                    temp_unit="C",
                    yes_price=market_price,
                    no_price=1.0 - market_price,
                    volume=0.0,
                )
            )

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
        if bucket.temp_unit == "F":
            obs_f = obs_c * 1.8 + 32.0
            low_f = bucket.temp_low_c * 1.8 + 32.0
            high_f = bucket.temp_high_c * 1.8 + 32.0
            return low_f <= obs_f <= high_f
        from math import floor

        return floor(obs_c) == bucket.temp_low_c
