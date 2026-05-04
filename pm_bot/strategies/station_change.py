from __future__ import annotations

import structlog

from pm_bot.models.market import Recommendation, TemperatureBucket, WeatherEvent
from pm_bot.models.config import CITY_COORDS
from pm_bot.strategies.base import Strategy

log = structlog.get_logger()


class StationChangeDetectorStrategy(Strategy):
    name = "station_change"

    def run(self, event: WeatherEvent, **kwargs) -> list[Recommendation]:
        defaults = self.get_defaults()
        bankroll = kwargs.get("bankroll", defaults.get("bankroll", 100.0))

        expected_coords = CITY_COORDS.get(event.city)
        if not expected_coords:
            return []

        event_airport = event.airport_code
        if not event_airport:
            event_airport = self._extract_airport_from_title(event.title)

        if not event_airport:
            return []

        expected_airport = self._find_airport_for_city(event.city)
        if not expected_airport:
            return []

        if event_airport.upper() == expected_airport.upper():
            return []

        mismatch_detected = True
        title_mentions_station = self._title_mentions_station(event.title, event_airport)

        if not mismatch_detected:
            return []

        recs: list[Recommendation] = []
        edge = 0.10
        if title_mentions_station:
            edge = 0.15

        best_bucket: TemperatureBucket | None = None
        for b in event.buckets:
            if b.yes_price > 0 and not b.is_low_tail and not b.is_high_tail:
                if best_bucket is None or b.yes_price > best_bucket.yes_price:
                    best_bucket = b

        if best_bucket is None and event.buckets:
            best_bucket = event.buckets[0]

        if best_bucket is None:
            return []

        recs.append(Recommendation(
            strategy=self.name,
            event=event,
            bucket=best_bucket,
            direction="YES",
            edge=edge,
            reasoning=(
                f"Station mismatch: event uses {event_airport} but expected {expected_airport} for {event.city}. "
                f"Other bots likely using stale coordinates for {expected_airport}."
            ),
            size_usd=bankroll * min(edge, 0.02),
            kelly_fraction=edge / (1.0 - best_bucket.yes_price) * 0.25 if best_bucket.yes_price < 1.0 else 0.0,
        ))

        return recs

    def _find_airport_for_city(self, city: str) -> str | None:
        from pm_bot.core.config_loader import load_config, get_station_for_city
        config = load_config()
        station = get_station_for_city(config, city)
        if station:
            icao = station.get("icao")
            if isinstance(icao, str):
                return icao
        return None

    def _extract_airport_from_title(self, title: str) -> str | None:
        import re
        m = re.search(r'\b([A-Z]{3,4})\b', title.upper())
        if m:
            return m.group(1)
        return None

    def _title_mentions_station(self, title: str, airport: str) -> bool:
        return airport.upper() in title.upper()
