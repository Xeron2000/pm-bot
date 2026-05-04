from __future__ import annotations

import math
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
PEAK_CUTOFF_HOUR = 17


@dataclass
class ObservedHigh:
    city: str
    observed_high_c: float
    obs_time_utc: datetime
    local_time: datetime
    is_past_peak: bool


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


async def fetch_observed_high(
    client: httpx.AsyncClient,
    city: str,
) -> ObservedHigh | None:
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

    is_past_peak = now_local.hour >= PEAK_CUTOFF_HOUR

    return ObservedHigh(
        city=city,
        observed_high_c=temp_c,
        obs_time_utc=obs_time_utc,
        local_time=now_local,
        is_past_peak=is_past_peak,
    )


def should_filter_bucket(
    bucket_temp_low_c: float,
    obs: ObservedHigh,
) -> bool:
    if not obs.is_past_peak:
        return False
    if bucket_temp_low_c == float("-inf"):
        return False
    floor_obs = math.floor(obs.observed_high_c)
    return bucket_temp_low_c < floor_obs


def filter_recommendations(
    recs: list,
    obs_high: ObservedHigh | None,
) -> list:
    if not obs_high or not obs_high.is_past_peak:
        return recs

    filtered = []
    for r in recs:
        if r.direction == "YES" and should_filter_bucket(r.bucket.temp_low, obs_high):
            log.debug(
                "filtering_impossible_yes",
                strategy=r.strategy,
                city=r.city,
                bucket_low_c=r.bucket.temp_low,
                observed_high_c=obs_high.observed_high_c,
                floor_obs=math.floor(obs_high.observed_high_c),
            )
            continue
        if r.direction == "NO" and not should_filter_bucket(r.bucket.temp_low, obs_high):
            if r.bucket.temp_low == math.floor(obs_high.observed_high_c):
                continue
        filtered.append(r)
    return filtered
