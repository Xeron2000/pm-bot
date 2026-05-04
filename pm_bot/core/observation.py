from __future__ import annotations

import math
import re
import structlog
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

log = structlog.get_logger()

CITY_ICAO: dict[str, str] = {
    "New York": "KLGA",
    "London": "EGLL",
    "Denver": "KDEN",
    "Helsinki": "EFHK",
    "Paris": "LFPB",
    "Tokyo": "RJTT",
    "Chicago": "KORD",
    "Austin": "KAUS",
    "Seoul": "RKSI",
    "Hong Kong": "VHHH",
    "Warsaw": "EPWA",
    "Lagos": "DNMM",
    "Taipei": "RCTP",
    "Miami": "KMIA",
}

CITY_TZ: dict[str, str] = {
    "New York": "America/New_York",
    "London": "Europe/London",
    "Denver": "America/Denver",
    "Helsinki": "Europe/Helsinki",
    "Paris": "Europe/Paris",
    "Tokyo": "Asia/Tokyo",
    "Chicago": "America/Chicago",
    "Austin": "America/Chicago",
    "Seoul": "Asia/Seoul",
    "Hong Kong": "Asia/Hong_Kong",
    "Warsaw": "Europe/Warsaw",
    "Lagos": "Africa/Lagos",
    "Taipei": "Asia/Taipei",
    "Miami": "America/New_York",
}

AWC_URL = "https://aviationweather.gov/api/data/metar"
HIGH_CUTOFF_HOUR = 17
LOW_CUTOFF_HOUR = 7
SPIKE_THRESHOLD_C = 3.0


@dataclass
class ObservedTemp:
    city: str
    observed_c: float
    obs_time_utc: datetime
    local_time: datetime
    is_past_cutoff: bool
    measure_type: str
    anomaly_detected: bool = False


ObservedHigh = ObservedTemp


async def fetch_metar_obs(
    client: httpx.AsyncClient,
    icao: str,
) -> Any:
    try:
        resp = await client.get(
            AWC_URL,
            params={"ids": icao, "format": "json", "taf": "false"},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None
        latest = data[0]
        return latest
    except Exception as e:
        log.warning("metar_fetch_failed", icao=icao, error=str(e))
        return None


async def fetch_previous_metar(
    client: httpx.AsyncClient,
    icao: str,
) -> Any:
    try:
        resp = await client.get(
            AWC_URL,
            params={"ids": icao, "format": "json", "taf": "false"},
        )
        resp.raise_for_status()
        data = resp.json()
        if len(data) < 2:
            return None
        return data[1]
    except Exception:
        return None


async def fetch_observation(
    client: httpx.AsyncClient,
    city: str,
    measure_type: str = "high",
) -> ObservedTemp | None:
    icao = CITY_ICAO.get(city)
    if not icao:
        log.debug("no_icao_for_city", city=city)
        return None

    tz_name = CITY_TZ.get(city, "UTC")
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)

    metar = await fetch_metar_obs(client, icao)
    if not metar:
        return None

    temp_c = metar.get("temp")
    if temp_c is None:
        return None

    try:
        temp_c = float(temp_c)
    except (ValueError, TypeError):
        return None

    obs_time_str = metar.get("obsTime", "")
    try:
        obs_time_utc = datetime.fromisoformat(obs_time_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        obs_time_utc = datetime.now(timezone.utc)

    cutoff_hour = LOW_CUTOFF_HOUR if measure_type == "low" else HIGH_CUTOFF_HOUR
    is_past_cutoff = now_local.hour >= cutoff_hour

    anomaly = False
    prev = await fetch_previous_metar(client, icao)
    if prev and prev.get("temp") is not None:
        try:
            prev_temp = float(prev["temp"])
            delta = abs(temp_c - prev_temp)
            if delta >= SPIKE_THRESHOLD_C:
                anomaly = True
                log.warning(
                    "temp_spike_anomaly",
                    city=city,
                    icao=icao,
                    current=temp_c,
                    previous=prev_temp,
                    delta=delta,
                )
        except (ValueError, TypeError):
            pass

    return ObservedTemp(
        city=city,
        observed_c=temp_c,
        obs_time_utc=obs_time_utc,
        local_time=now_local,
        is_past_cutoff=is_past_cutoff,
        measure_type=measure_type,
        anomaly_detected=anomaly,
    )


async def fetch_observed_high(
    client: httpx.AsyncClient,
    city: str,
) -> ObservedHigh | None:
    return await fetch_observation(client, city, measure_type="high")


def resolve_icao_from_description(description: str) -> str | None:
    pattern = r"wunderground\.com/[^/]+/[^/]+/[^/]+/[^/]+/([A-Z]{4})"
    m = re.search(pattern, description, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return None


def get_icao(city: str, description: str | None = None) -> str | None:
    if description:
        dynamic = resolve_icao_from_description(description)
        if dynamic:
            if dynamic != CITY_ICAO.get(city):
                log.info("icao_dynamic_override", city=city, static=CITY_ICAO.get(city), dynamic=dynamic)
            return dynamic
    return CITY_ICAO.get(city)


def should_filter_bucket(
    bucket_temp_low_c: float,
    obs: ObservedTemp,
) -> bool:
    if not obs.is_past_cutoff:
        return False
    if bucket_temp_low_c == float("-inf"):
        return False
    if obs.measure_type == "low":
        floor_obs = math.floor(obs.observed_c)
        return bucket_temp_low_c > floor_obs
    floor_obs = math.floor(obs.observed_c)
    return bucket_temp_low_c < floor_obs


def filter_recommendations(
    recs: list,
    obs: ObservedTemp | None,
) -> list:
    if not obs or not obs.is_past_cutoff:
        return recs

    filtered = []
    for r in recs:
        if r.direction == "YES" and should_filter_bucket(r.bucket.temp_low, obs):
            log.debug(
                "filtering_impossible_yes",
                strategy=r.strategy,
                city=r.city,
                bucket_low_c=r.bucket.temp_low,
                observed_c=obs.observed_c,
                measure_type=obs.measure_type,
            )
            continue
        if r.direction == "NO" and not should_filter_bucket(r.bucket.temp_low, obs):
            floor_obs = math.floor(obs.observed_c)
            if r.bucket.temp_low == floor_obs:
                log.debug(
                    "filtering_confirmed_no",
                    strategy=r.strategy,
                    city=r.city,
                    bucket_low_c=r.bucket.temp_low,
                    floor_obs=floor_obs,
                )
                continue
        filtered.append(r)
    return filtered
