from __future__ import annotations

import math

import httpx
import structlog

from pm_bot.models.forecast import ConsensusForecast, SourceForecast
from pm_bot.models.market import ForecastResult
from pm_bot.core.sources.nws import fetch_nws_forecast
from pm_bot.core.sources.metar import fetch_metar, get_icao_for_city

log = structlog.get_logger()


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bucket_probability_normal(mean: float, std: float, low: float, high: float, temp_unit: str = "C") -> float:
    if std <= 0:
        std = 0.5
    z_low = (low - mean) / std
    if temp_unit == "F":
        z_high = (high + 1.0 / 1.8 - mean) / std
    else:
        z_high = (low + 1.0 - mean) / std
    return max(0.0, min(1.0, _norm_cdf(z_high) - _norm_cdf(z_low)))


def compute_bma_weights(sources: list[SourceForecast]) -> list[float]:
    if not sources:
        return []
    inv_sq = [1.0 / max(s.std**2, 0.01) for s in sources]
    total = sum(inv_sq)
    return [w / total for w in inv_sq]


def compute_consensus_probability(
    sources: list[SourceForecast],
    temp_low_c: float,
    temp_high_c: float,
    temp_unit: str = "C",
) -> float:
    if not sources:
        return 0.5
    weights = compute_bma_weights(sources)
    total_prob = 0.0
    for s, w in zip(sources, weights):
        std = max(s.std, 0.5)
        p = bucket_probability_normal(s.mean, std, temp_low_c, temp_high_c, temp_unit)
        total_prob += w * p
    return max(0.0, min(1.0, total_prob))


def compute_agreement_score(sources: list[SourceForecast]) -> float:
    if len(sources) < 2:
        return 0.5
    means = [s.mean for s in sources]
    spread = max(means) - min(means)
    return max(0.0, min(1.0, 1.0 - spread / 5.0))


async def fetch_all_sources(
    client: httpx.AsyncClient,
    city: str,
    date: str,
    config: dict,
    open_meteo_forecast: ForecastResult | None = None,
) -> ConsensusForecast:
    sources: list[SourceForecast] = []
    individual_probs: dict[str, float] = {}

    if open_meteo_forecast:
        om_src = SourceForecast(
            source="open_meteo",
            temp_high_c=open_meteo_forecast.temp_high_c,
            std_c=open_meteo_forecast.std if open_meteo_forecast.std > 0 else 1.5,
            weight=2.0,
            members=open_meteo_forecast.members,
        )
        sources.append(om_src)
        individual_probs["open_meteo"] = open_meteo_forecast.temp_high_c

    try:
        nws_data = await fetch_nws_forecast(client, city, date)
        if nws_data:
            nws_src = SourceForecast(
                source="nws",
                temp_high_c=nws_data["temp_high_c"],
                std_c=nws_data.get("std_c", 2.0),
                weight=1.5,
            )
            sources.append(nws_src)
            individual_probs["nws"] = nws_data["temp_high_c"]
    except Exception as e:
        log.warning("nws_source_failed", city=city, error=str(e))

    icao = get_icao_for_city(config, city)
    if icao:
        try:
            metar_data = await fetch_metar(client, icao)
            if metar_data:
                metar_src = SourceForecast(
                    source="metar",
                    temp_high_c=metar_data["temp_c"],
                    std_c=1.0,
                    weight=1.0,
                )
                sources.append(metar_src)
                individual_probs["metar"] = metar_data["temp_c"]
        except Exception as e:
            log.warning("metar_source_failed", city=city, icao=icao, error=str(e))

    if not sources:
        return ConsensusForecast(
            city=city,
            date=date,
            temp_high_c=0.0,
            std_c=5.0,
            consensus_prob=0.5,
            agreement_score=0.0,
            sources={},
            individual_probs=individual_probs,
        )

    weights = compute_bma_weights(sources)
    bma_mean = sum(w * s.mean for w, s in zip(weights, sources))
    bma_var = sum(w * (s.std**2 + (s.mean - bma_mean) ** 2) for w, s in zip(weights, sources))
    bma_std = math.sqrt(max(bma_var, 0.01))

    agreement = compute_agreement_score(sources)
    sources_dict = {s.source: s for s in sources}

    return ConsensusForecast(
        city=city,
        date=date,
        temp_high_c=bma_mean,
        std_c=bma_std,
        consensus_prob=0.5,
        agreement_score=agreement,
        sources=sources_dict,
        individual_probs=individual_probs,
    )


def consensus_bucket_probability(
    consensus: ConsensusForecast,
    temp_low_c: float,
    temp_high_c: float,
    temp_unit: str = "C",
) -> float:
    sources = list(consensus.sources.values())
    if not sources:
        return 0.5
    prob = compute_consensus_probability(sources, temp_low_c, temp_high_c, temp_unit)
    # PRD 3B: 3+ source agreement → edge confidence ×1.5~2.0
    n_sources = len(sources)
    if n_sources >= 3 and consensus.agreement_score >= 0.8:
        # 3+ sources in strong agreement: scale probability toward extreme
        if prob >= 0.5:
            prob = min(1.0, prob * 1.5)
        else:
            prob = max(0.0, 1.0 - (1.0 - prob) * 1.5)
    elif n_sources >= 2 and consensus.agreement_score >= 0.8:
        prob = min(1.0, prob * 1.25) if prob >= 0.5 else max(0.0, 1.0 - (1.0 - prob) * 1.25)
    # PRD 3B: Source disagreement → lower Kelly fraction
    if consensus.agreement_score < 0.4:
        prob = prob * max(consensus.agreement_score, 0.3)
    return max(0.0, min(1.0, prob))
