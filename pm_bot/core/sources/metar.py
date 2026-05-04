from __future__ import annotations

import httpx
import structlog
from cachetools import TTLCache

log = structlog.get_logger()

AWC_BASE = "https://aviationweather.gov/api/data"
USER_AGENT = "pm-bot/1.0"

_metar_cache: TTLCache[str, dict] = TTLCache(maxsize=128, ttl=300)


async def fetch_metar(
    client: httpx.AsyncClient,
    icao: str,
) -> dict | None:
    if not icao or len(icao) != 4:
        return None

    cache_key = f"metar:{icao}"
    if cache_key in _metar_cache:
        return _metar_cache[cache_key]

    try:
        resp = await client.get(
            f"{AWC_BASE}/metar",
            params={"ids": icao, "format": "json"},
            headers={"User-Agent": USER_AGENT},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        log.warning("metar_fetch_failed", icao=icao, error=str(e))
        return None

    features = data if isinstance(data, list) else data.get("features", [])
    if not features:
        return None

    latest = features[0] if isinstance(features[0], dict) else {}
    temp_c = latest.get("temp")
    if temp_c is None:
        raw = latest.get("rawText", "")
        temp_c = _parse_temp_from_raw(raw)

    if temp_c is None:
        return None

    result = {
        "icao": icao,
        "source": "metar",
        "temp_c": float(temp_c),
        "observation_time": latest.get("observationTime", ""),
    }
    _metar_cache[cache_key] = result
    return result


def _parse_temp_from_raw(raw: str) -> float | None:
    import re
    m = re.search(r"\s(M?\d{2})/(M?\d{2})\s", raw)
    if not m:
        return None
    temp_str = m.group(1).replace("M", "-")
    try:
        return float(temp_str)
    except ValueError:
        return None


def get_icao_for_city(config: dict, city: str) -> str | None:
    stations = config.get("stations", {})
    for icao, info in stations.items():
        if info.get("city", "").lower() == city.lower():
            return str(icao)
    return None
