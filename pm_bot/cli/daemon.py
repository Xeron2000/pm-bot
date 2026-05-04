from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import httpx
import structlog
from rich.console import Console
from rich.table import Table

from pm_bot.core.aggregation import fetch_all_sources
from pm_bot.core.clob import ClobTrader
from pm_bot.core.config_loader import (
    get_sizing,
    get_station_for_city,
    load_config,
    get_notifications,
)
from pm_bot.core.db import TradeDB
from pm_bot.core.kelly import compute_kelly_for_recommendation
from pm_bot.core.polymarket import fetch_weather_events
from pm_bot.core.risk import RiskManager, RiskCheckResult
from pm_bot.core.weather import fetch_forecast
from pm_bot.core.observation import fetch_observed_high, filter_recommendations
from pm_bot.models.config import DEFAULT_CITIES, STRATEGY_DEFAULTS, resolve_city_alias, CITY_COORDS
from pm_bot.models.forecast import ConsensusForecast
from pm_bot.models.market import Recommendation, ForecastResult
from pm_bot.strategies.base import ALL_STRATEGIES
from pm_bot.cli.notifications import notify, send_discord, send_telegram, format_daemon_message

console = Console()
log = structlog.get_logger()

PID_FILE = Path.home() / ".pm-bot" / "daemon.pid"
HEARTBEAT_FILE = Path.home() / ".pm-bot" / "heartbeat"
CONFIG_RELOAD_FLAG = Path.home() / ".pm-bot" / ".reload_config"


class TradingDaemon:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.db = TradeDB()
        sizing = get_sizing(config)
        risk_cfg = config.get("risk", {})
        daemon_cfg = config.get("daemon", {})

        self.trader = ClobTrader(config)
        self.bankroll = float(os.environ.get("PM_BOT_BANKROLL", sizing.get("bankroll", 500.0)))
        self.kelly_fraction_val = float(os.environ.get("PM_BOT_KELLY", sizing.get("kelly_fraction", 0.25)))
        self.max_single = float(os.environ.get("PM_BOT_MAX_SINGLE", sizing.get("max_single", 50.0)))
        self.max_daily = float(os.environ.get("PM_BOT_MAX_DAILY", sizing.get("max_daily", 200.0)))
        self.max_per_city = float(os.environ.get("PM_BOT_MAX_PER_CITY", sizing.get("max_per_city", 100.0)))
        self.max_total_pct = float(os.environ.get("PM_BOT_MAX_TOTAL_PCT", sizing.get("max_total_pct", 0.30)))
        self.scan_interval = int(daemon_cfg.get("scan_interval", 300))
        self.heartbeat_path = Path(os.environ.get("PM_BOT_HEARTBEAT", daemon_cfg.get("heartbeat_path", str(HEARTBEAT_FILE)))).expanduser()

        self.risk_manager = RiskManager(
            db=self.db,
            bankroll=self.bankroll,
            circuit_breaker_l1=float(risk_cfg.get("circuit_breaker_l1", 0.05)),
            circuit_breaker_l2=float(risk_cfg.get("circuit_breaker_l2", 0.10)),
            circuit_breaker_l3=float(risk_cfg.get("circuit_breaker_l3", 0.15)),
            no_new_before_resolution_h=int(risk_cfg.get("no_new_position_before_resolution_h", 6)),
            consecutive_loss_pause_count=int(risk_cfg.get("consecutive_loss_pause_count", 5)),
            consecutive_loss_pause_minutes=int(risk_cfg.get("consecutive_loss_pause_minutes", 60)),
            max_spread=float(risk_cfg.get("max_spread", 0.10)),
            max_per_city=self.max_per_city,
            max_total_pct=self.max_total_pct,
            max_daily=self.max_daily,
        )

        self.shutdown_event = asyncio.Event()
        self.start_time = time.time()
        self.cycle_count = 0
        self.trades_this_cycle = 0

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, self._handle_sigterm)
        loop.add_signal_handler(signal.SIGINT, self._handle_sigterm)
        try:
            loop.add_signal_handler(signal.SIGUSR1, self._handle_sigusr1)
        except (OSError, AttributeError):
            pass

        self._write_pid()
        await self._send_notification("🟢 PM-Bot daemon started", "daemon_start")

        if not self.trader.is_configured():
            log.error("trader_not_configured")
            await self._send_notification("🔴 PM-Bot daemon: trading credentials not configured", "daemon_error")
            return

        self.trader.start_heartbeat()

        try:
            self._recover_state()
            while not self.shutdown_event.is_set():
                cycle_start = time.time()
                try:
                    await self._trade_cycle()
                except Exception as e:
                    log.error("cycle_failed", error=str(e))
                self.cycle_count += 1
                self._write_heartbeat()

                self._check_daily_reset()

                elapsed = time.time() - cycle_start
                sleep_time = max(0, self.scan_interval - elapsed)
                try:
                    await asyncio.wait_for(self.shutdown_event.wait(), timeout=sleep_time)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self._graceful_shutdown()

    async def _trade_cycle(self) -> None:
        self.trades_this_cycle = 0
        async with httpx.AsyncClient(timeout=30.0) as client:
            events = await fetch_weather_events(client)
            events = [e for e in events if e.city in {resolve_city_alias(c) for c in DEFAULT_CITIES}]

            if not events:
                log.debug("no_events_found")
                return

            forecasts: dict[str, ForecastResult] = {}
            consensus_forecasts: dict[str, Any] = {}
            obs_highs: dict[str, Any] = {}
            for ev in events:
                fc = await fetch_forecast(client, ev.city, ev.date)
                if fc:
                    forecasts[ev.city] = fc
                cf = await fetch_all_sources(client, ev.city, ev.date, self.config, fc)
                consensus_forecasts[ev.city] = cf

            for city in {ev.city for ev in events}:
                obs = await fetch_observed_high(client, city)
                if obs:
                    obs_highs[city] = obs
                    if obs.is_past_peak:
                        log.info("observed_high_locked", city=city, high_c=obs.observed_high_c)

            all_recs: list[Recommendation] = []
            for ev in events:
                for strat_name, strat in ALL_STRATEGIES.items():
                    kwargs: dict[str, Any] = {}
                    for k, v in STRATEGY_DEFAULTS.get(strat_name, {}).items():
                        kwargs[k] = v
                    if strat_name in ("truncation_edge", "ensemble_spread") and ev.city in forecasts:
                        kwargs["forecast"] = forecasts[ev.city]
                    if strat_name == "ensemble_spread":
                        kwargs["config"] = self.config
                        station_info = get_station_for_city(self.config, ev.city)
                        if station_info:
                            lat = station_info.get("lat")
                            lon = station_info.get("lon")
                            if lat is not None and lon is not None:
                                kwargs["airport_forecast"] = await _fetch_forecast_at(
                                    client, float(lat), float(lon), ev.city, ev.date
                                )
                        city_coords = CITY_COORDS.get(ev.city)
                        if city_coords:
                            kwargs["city_forecast"] = await _fetch_forecast_at(
                                client, city_coords[0], city_coords[1], ev.city, ev.date
                            )

                    recs = strat.run(ev, **kwargs)

                    if ev.city in obs_highs:
                        recs = filter_recommendations(recs, obs_highs[ev.city])

                    for rec in recs:
                        if rec.edge < 0.05:
                            continue
                        if self.db.check_duplicate_order(rec.bucket.market_id, rec.direction):
                            continue

                        # PRD 3B: Apply consensus agreement to edge/Kelly
                        consensus: ConsensusForecast | None = consensus_forecasts.get(rec.city)
                        agreement_adj = 1.0
                        if consensus and consensus.sources:
                            # Recompute edge using consensus probability if available
                            if consensus.agreement_score >= 0.8 and len(consensus.sources) >= 3:
                                agreement_adj = 1.5  # 3+ source agreement → ×1.5
                            elif consensus.agreement_score >= 0.6 and len(consensus.sources) >= 2:
                                agreement_adj = 1.25
                            elif consensus.agreement_score < 0.4:
                                agreement_adj = consensus.agreement_score  # disagreement → reduce

                        risk_result = self.risk_manager.full_check(
                            city=rec.city,
                            amount_usd=self.max_single,
                            yes_price=rec.bucket.yes_price,
                            no_price=rec.bucket.no_price,
                            hours_to_resolution=_estimate_hours_to_resolution(ev.date),
                        )
                        if not risk_result.allowed:
                            log.info("risk_blocked", reason=risk_result.reason, city=rec.city)
                            # PRD 3E/3F: Send circuit breaker / consecutive loss notification
                            if risk_result.circuit_breaker_level > 0:
                                await self.send_circuit_breaker_alert(risk_result)
                            elif "Consecutive" in risk_result.reason:
                                await self._send_notification(
                                    f"⚠️ {risk_result.reason}\nBankroll: ${self.bankroll:.2f}",
                                    "consecutive_loss",
                                )
                            continue

                        effective_kelly = self.kelly_fraction_val * risk_result.kelly_adjustment * agreement_adj
                        daily_spent = self.db.get_daily_spent()
                        city_spent = self.db.get_city_spent(rec.city)
                        total_exposure = self.db.get_total_exposure()

                        sized = compute_kelly_for_recommendation(
                            rec,
                            bankroll=self.bankroll,
                            kelly_multiplier=effective_kelly,
                            max_single=self.max_single,
                            max_daily=self.max_daily,
                            daily_spent=daily_spent,
                            max_per_city=self.max_per_city,
                            city_spent=city_spent,
                            max_total_pct=self.max_total_pct,
                            total_exposure=total_exposure,
                        )
                        if sized is not None:
                            all_recs.append(sized)

            all_recs.sort(key=lambda r: r.edge, reverse=True)

            for rec in all_recs:
                if self.trades_this_cycle >= 10:
                    break
                await self._execute_trade(rec)

    async def _execute_trade(self, rec: Recommendation) -> None:
        bucket = rec.bucket
        price = rec.price
        size_usd = rec.size_usd

        if size_usd < 1.0:
            return

        size_shares = size_usd / price if price > 0 else 1

        if rec.direction == "YES":
            result = self.trader.place_limit_buy(
                token_id=bucket.market_id,
                price=price,
                size=size_shares,
                neg_risk=True,
            )
        else:
            result = self.trader.place_limit_sell(
                token_id=bucket.market_id,
                price=price,
                size=size_shares,
                neg_risk=True,
            )

        if result:
            order_id = str(result.get("orderID", result.get("order_id", "")))
            self.db.record_trade(
                order_id=order_id,
                market_id=bucket.market_id,
                side=rec.direction,
                price=price,
                amount_usd=size_usd,
                strategy=rec.strategy,
                edge=rec.edge,
                city=rec.city,
                temp_label=rec.temp_label,
                kelly_fraction_val=rec.kelly_fraction,
                reasoning=rec.reasoning,
            )
            self.trades_this_cycle += 1
            log.info(
                "auto_trade",
                strategy=rec.strategy,
                city=rec.city,
                direction=rec.direction,
                temp_label=rec.temp_label,
                price=price,
                size_usd=size_usd,
                edge=rec.edge,
                order_id=order_id[:16],
            )
            await notify(
                self.config, "created", rec.strategy, rec.direction,
                rec.city, rec.temp_label, price, rec.edge, order_id,
            )
        else:
            log.warning("auto_trade_failed", city=rec.city, direction=rec.direction)

    def _recover_state(self) -> None:
        # PRD 3D: Check for crash recovery from previous run
        shutdown_state = self.db.get_state_json("shutdown_state")
        had_graceful_shutdown = self.db.get_state("graceful_shutdown") == "true"

        try:
            open_orders = self.trader.get_open_orders()
            api_ids = {str(o.get("id", o.get("orderID", ""))) for o in open_orders}
            self.db.reconcile_open_orders(api_ids)
            log.info("state_recovered", open_orders=len(open_orders))
        except Exception as e:
            log.warning("state_recovery_failed", error=str(e))

        # PRD 3F: Notify if crash recovery (no graceful shutdown flag)
        if not had_graceful_shutdown and shutdown_state:
            log.warning("crash_recovery_detected")
            asyncio.create_task(
                self._send_notification(
                    format_daemon_message("crash_recovery", "Reconciling with Polymarket API"),
                    "crash_recovery",
                )
            )

        # Reset graceful shutdown flag so next crash is detected
        self.db.set_state("graceful_shutdown", "false")

    async def _graceful_shutdown(self) -> None:
        log.info("graceful_shutdown_start")

        try:
            self.trader.cancel_all_orders()
            log.info("all_orders_cancelled")
        except Exception as e:
            log.error("cancel_all_failed", error=str(e))

        self._persist_state()

        # Mark graceful shutdown for crash recovery detection
        self.db.set_state("graceful_shutdown", "true")

        pending = self.db.get_open_trades()
        if pending:
            log.info("waiting_pending_fills", count=len(pending))
            try:
                await asyncio.wait_for(self._poll_fills(), timeout=30)
            except asyncio.TimeoutError:
                log.warning("pending_fill_timeout")

        self.trader.stop_heartbeat()

        self._update_daily_state()

        await self._send_notification("🔴 PM-Bot daemon stopped", "daemon_stop")

        self._remove_pid()
        self.db.close()
        log.info("graceful_shutdown_complete")

    async def _poll_fills(self) -> None:
        open_trades = self.db.get_open_trades()
        for t in open_trades:
            order_id = t.get("order_id", "")
            if not order_id:
                continue
            status = self.trader.get_order_status(order_id)
            if status:
                fill_status = status.get("status", "open")
                if fill_status in ("filled", "matched"):
                    self.db.update_fill_status(order_id, "filled")
                elif fill_status in ("cancelled",):
                    self.db.update_fill_status(order_id, "cancelled")

    def _persist_state(self) -> None:
        daily_spent = self.db.get_daily_spent()
        self.db.set_state_json("shutdown_state", {
            "daily_spent": daily_spent,
            "bankroll": self.bankroll,
            "last_cycle": time.time(),
        })

    def _update_daily_state(self) -> None:
        daily_spent = self.db.get_daily_spent()
        daily_pnl = self.db.get_daily_pnl()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        trades = self.db.get_recent_trades(limit=100)
        today_trades = [t for t in trades if t.get("created_at", "").startswith(today)]
        wins = sum(1 for t in today_trades if t.get("edge", 0) > 0)
        losses = len(today_trades) - wins
        self.db.update_daily_state(
            date=today,
            total_spent=daily_spent,
            total_pnl=daily_pnl,
            trade_count=len(today_trades),
            win_count=wins,
            loss_count=losses,
            bankroll_end=self.bankroll + daily_pnl,
        )

    def _check_daily_reset(self) -> None:
        state = self.db.get_state_json("daily_reset")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if state and state.get("date") == today:
            return

        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        self._update_daily_state()

        daily_state = self.db.get_daily_state(yesterday)
        pnl = daily_state.get("total_pnl", 0)
        trades = daily_state.get("trade_count", 0)
        wins = daily_state.get("win_count", 0)

        msg = (
            f"📊 <b>Daily Summary — {yesterday}</b>\n"
            f"  P&L: ${pnl:.2f}\n"
            f"  Trades: {trades} (W:{wins} L:{trades - wins})\n"
            f"  Bankroll: ${self.bankroll:.2f}\n"
        )
        asyncio.create_task(self._send_notification(msg, "daily_summary"))

        self.db.set_state_json("daily_reset", {"date": today})

    def _write_heartbeat(self) -> None:
        try:
            self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            self.heartbeat_path.write_text(json.dumps({
                "ts": time.time(),
                "status": "running",
                "cycle": self.cycle_count,
                "trades_this_cycle": self.trades_this_cycle,
                "daily_spent": self.db.get_daily_spent(),
                "bankroll": self.bankroll,
                "pid": os.getpid(),
                "uptime": time.time() - self.start_time,
            }))
        except Exception as e:
            log.warning("heartbeat_write_failed", error=str(e))

    def _write_pid(self) -> None:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))

    def _remove_pid(self) -> None:
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    def _handle_sigterm(self) -> None:
        log.info("sigterm_received")
        self.shutdown_event.set()

    def _handle_sigusr1(self) -> None:
        log.info("sigusr1_reload_config")
        try:
            self.config = load_config()
            log.info("config_reloaded")
        except Exception as e:
            log.error("config_reload_failed", error=str(e))

    async def _send_notification(self, msg: str, event_type: str) -> None:
        notifications = get_notifications(self.config)
        discord = notifications.get("discord", {})
        telegram = notifications.get("telegram", {})
        await send_discord(discord.get("webhook_url", ""), msg)
        await send_telegram(telegram.get("bot_token", ""), str(telegram.get("chat_id", "")), msg)

    async def send_circuit_breaker_alert(self, result: RiskCheckResult) -> None:
        level_emoji = {1: "🟡", 2: "🟠", 3: "🔴"}.get(result.circuit_breaker_level, "⚪")
        msg = (
            f"{level_emoji} [L{result.circuit_breaker_level} CIRCUIT BREAKER]\n"
            f"{result.reason}\n"
            f"Bankroll: ${self.bankroll:.2f} | Kelly adj: {result.kelly_adjustment:.0%}"
        )
        await self._send_notification(msg, "circuit_breaker")


async def _fetch_forecast_at(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
    city: str,
    date: str = "",
    model: str = "gfs_seamless",
) -> ForecastResult | None:
    from pm_bot.core.weather import OPEN_METEO_BASE, ENSEMBLE_BASE, _MEMBER_KEYS

    params: dict[str, str | int | float] = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max",
        "forecast_days": 3,
        "timezone": "auto",
    }
    try:
        params_model = {**params, "models": model}
        resp = await client.get(f"{OPEN_METEO_BASE}/forecast", params=params_model)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        log.error("forecast_at_error", lat=lat, lon=lon, error=str(e))
        return None

    daily = data.get("daily", {})
    temps = daily.get("temperature_2m_max", [])
    main_temp = float(temps[0]) if temps and isinstance(temps[0], (int, float)) else 0.0

    members: list[float] = []
    try:
        params_ens = {**params, "models": model}
        resp = await client.get(ENSEMBLE_BASE, params=params_ens)
        resp.raise_for_status()
        ens_data = resp.json()
        ens_daily = ens_data.get("daily", {})
        for mk in _MEMBER_KEYS:
            member_data = ens_daily.get(mk, [])
            if member_data:
                v = member_data[0]
                if isinstance(v, (int, float)):
                    members.append(float(v))
    except httpx.HTTPError:
        pass

    return ForecastResult(
        city=city,
        date=date,
        model=model,
        temp_high_c=main_temp,
        members=members,
    )


def _is_daemon_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        PID_FILE.unlink(missing_ok=True)
        return False


def _estimate_hours_to_resolution(date_str: str) -> float | None:
    """Estimate hours until market resolution (usually midnight ET on the date)."""
    if not date_str:
        return None
    try:
        # Weather markets typically resolve at midnight US Eastern time
        resolution = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=5, minute=0, second=0  # UTC 05:00 ≈ midnight ET
        ).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = (resolution - now).total_seconds() / 3600.0
        return max(0.0, delta)
    except (ValueError, TypeError):
        return None


async def daemon_start(debug: bool = False) -> None:
    _setup_logging(debug)

    if _is_daemon_running():
        pid = PID_FILE.read_text().strip()
        console.print(f"[red]Daemon already running (PID {pid})[/red]")
        return

    config = load_config()
    daemon = TradingDaemon(config)

    if not daemon.trader.is_configured():
        console.print("[red]Trading credentials not configured. Set POLY_PK and [clob] in config.toml[/red]")
        return

    console.print("[bold green]Starting PM-Bot daemon...[/bold green]")
    await daemon.run()


async def daemon_stop(debug: bool = False) -> None:
    _setup_logging(debug)

    if not _is_daemon_running():
        console.print("[yellow]Daemon is not running[/yellow]")
        return

    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        console.print(f"[green]Sent SIGTERM to daemon (PID {pid})[/green]")
    except ProcessLookupError:
        console.print("[yellow]Daemon process not found (stale PID file)[/yellow]")
        PID_FILE.unlink(missing_ok=True)
    except PermissionError:
        console.print("[red]Permission denied to send signal[/red]")


async def daemon_status(debug: bool = False) -> None:
    _setup_logging(debug)

    if not _is_daemon_running():
        console.print("[yellow]Daemon is not running[/yellow]")
        return

    pid = PID_FILE.read_text().strip()

    hb_data: dict[str, Any] = {}
    if HEARTBEAT_FILE.exists():
        try:
            hb_data = json.loads(HEARTBEAT_FILE.read_text())
        except (json.JSONDecodeError, ValueError):
            pass

    db = TradeDB()
    try:
        daily_spent = db.get_daily_spent()
        daily_pnl = db.get_daily_pnl()
        open_trades = len(db.get_open_trades())
        total_exposure = db.get_total_exposure()
    except Exception:
        daily_spent = 0.0
        daily_pnl = 0.0
        open_trades = 0
        total_exposure = 0.0
    finally:
        db.close()

    table = Table(title="PM-Bot Daemon Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    uptime = hb_data.get("uptime", 0)
    hours, remainder = divmod(int(uptime), 3600)
    minutes, seconds = divmod(remainder, 60)

    table.add_row("PID", pid)
    table.add_row("Uptime", f"{hours}h {minutes}m {seconds}s")
    table.add_row("Cycles", str(hb_data.get("cycle", 0)))
    table.add_row("Bankroll", f"${hb_data.get('bankroll', 0):.2f}")
    table.add_row("Daily Spent", f"${daily_spent:.2f}")
    table.add_row("Daily P&L", f"${daily_pnl:.2f}")
    table.add_row("Open Orders", str(open_trades))
    table.add_row("Total Exposure", f"${total_exposure:.2f}")
    table.add_row("Last Heartbeat", datetime.fromtimestamp(hb_data.get("ts", 0)).strftime("%H:%M:%S") if hb_data.get("ts") else "N/A")

    console.print(table)


def _setup_logging(debug: bool) -> None:
    import logging
    if debug:
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG))
    else:
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
