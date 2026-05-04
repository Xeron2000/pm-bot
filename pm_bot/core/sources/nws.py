from __future__ import annotations

import httpx
import structlog
from cachetools import TTLCache

from pm_bot.models.config import CITY_COORDS

log = structlog.get_logger()

NWS_BASE = "https://api.weather.gov"
USER_AGENT = "pm-bot/1.0"

_nws_cache: TTLCache[str, dict] = TTLCache(maxsize=128, ttl=900)


async def fetch_nws_forecast(
    client: httpx.AsyncClient,
    city: str,
    date: str = "",
) -> dict | None:
    coords = CITY_COORDS.get(city)
    if not coords:
        log.warning("nws_unknown_city", city=city)
        return None

    lat, lon = coords
    cache_key = f"nws:{city}"
    if cache_key in _nws_cache:
        return _nws_cache[cache_key]

    try:
        resp = await client.get(
            f"{NWS_BASE}/points/{lat:.4f},{lon:.4f}",
            headers={"User-Agent": USER_AGENT},
            timeout=15.0,
        )
        resp.raise_for_status()
        grid_data = resp.json()
    except httpx.HTTPError as e:
        log.warning("nws_points_failed", city=city, error=str(e))
        return None

    props = grid_data.get("properties", {})
    hourly_url = props.get("forecastHourly")
    if not hourly_url:
        log.warning("nws_no_hourly_url", city=city)
        return None

    try:
        resp = await client.get(hourly_url, headers={"User-Agent": USER_AGENT}, timeout=15.0)
        resp.raise_for_status()
        forecast_data = resp.json()
    except httpx.HTTPError as e:
        log.warning("nws_hourly_failed", city=city, error=str(e))
        return None

    result = _parse_nws_hourly(forecast_data, city, date)
    if result:
        _nws_cache[cache_key] = result
    return result


def _parse_nws_hourly(data: dict, city: str, date: str) -> dict | None:
    periods = data.get("properties", {}).get("periods", [])
    if not periods:
        return None

    max_temp_c = float("-inf")
    for p in periods:
        temp_f = p.get("temperature")
        if temp_f is None:
            continue
        temp_c = (temp_f - 32) / 1.8
        if temp_c > max_temp_c:
            max_temp_c = temp_c

    if max_temp_c == float("-inf"):
        return None

    return {
        "city": city,
        "date": date,
        "source": "nws",
        "temp_high_c": max_temp_c,
        "std_c": 2.0,
    }
