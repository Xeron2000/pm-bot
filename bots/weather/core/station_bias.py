from __future__ import annotations

import json
import structlog
from dataclasses import dataclass, field
from pathlib import Path

log = structlog.get_logger()

BIAS_DB_PATH = Path.home() / ".pm_bot" / "station_bias.json"
DEFAULT_ALPHA = 0.15
WARMUP_DAYS = 30

# Known bias priors from ERA5 cold-bias correction data.
# Used as initial estimates before enough observations accumulate.
STATION_PRIORS: dict[str, float] = {
    "New York": 0.7,
    "London": 0.8,
    "Hong Kong": 0.5,
    "Miami": 0.6,
    "Dallas": 1.1,
    "Seoul": 0.9,
    "Tokyo": 0.8,
    "Shanghai": 0.9,
    "Beijing": 0.9,
    "Paris": 0.7,
}


@dataclass
class StationBiasEntry:
    """Single station/lead-time bias tracking entry using EMA."""

    station: str
    lead_time_bucket: str
    bias_c: float = 0.0
    sample_count: int = 0

    def update(self, observed_c: float, predicted_c: float, alpha: float = DEFAULT_ALPHA) -> None:
        """Update the EMA bias with a new observation."""
        error = observed_c - predicted_c
        self.bias_c = alpha * error + (1.0 - alpha) * self.bias_c
        self.sample_count += 1


@dataclass
class StationBiasDB:
    """Database of per-station, per-lead-time bias entries.

    During warmup (fewer than WARMUP_DAYS observations), falls back to
    STATION_PRIORS for known stations to avoid returning zero bias.
    """

    entries: dict[str, StationBiasEntry] = field(default_factory=dict)
    alpha: float = DEFAULT_ALPHA

    def get_bias(self, station: str, lead_time_hours: int = 24) -> float:
        """Return the current bias estimate for a station.

        Returns the EMA bias once warmup completes, otherwise the prior
        from STATION_PRIORS if available, or 0.0 as a last resort.
        """
        bucket = _lead_time_bucket(lead_time_hours)
        key = f"{station}:{bucket}"
        entry = self.entries.get(key)
        if entry is None or entry.sample_count < WARMUP_DAYS:
            return STATION_PRIORS.get(station, 0.0)
        return entry.bias_c

    def record(self, station: str, observed_c: float, predicted_c: float, lead_time_hours: int = 24) -> None:
        bucket = _lead_time_bucket(lead_time_hours)
        key = f"{station}:{bucket}"
        if key not in self.entries:
            self.entries[key] = StationBiasEntry(station=station, lead_time_bucket=bucket)
        self.entries[key].update(observed_c, predicted_c, self.alpha)

    def apply_correction(self, predicted_c: float, station: str, lead_time_hours: int = 24) -> float:
        bias = self.get_bias(station, lead_time_hours)
        return predicted_c + bias

    def save(self, path: Path | None = None) -> None:
        path = path or BIAS_DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for key, entry in self.entries.items():
            data[key] = {
                "bias_c": entry.bias_c,
                "sample_count": entry.sample_count,
                "station": entry.station,
                "lead_time_bucket": entry.lead_time_bucket,
            }
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: Path | None = None) -> StationBiasDB:
        path = path or BIAS_DB_PATH
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
            db = cls()
            for key, val in data.items():
                db.entries[key] = StationBiasEntry(
                    station=val["station"],
                    lead_time_bucket=val["lead_time_bucket"],
                    bias_c=val["bias_c"],
                    sample_count=val["sample_count"],
                )
            return db
        except (json.JSONDecodeError, KeyError) as e:
            log.warning("bias_db_load_failed", error=str(e))
            return cls()


def _lead_time_bucket(hours: int) -> str:
    """Map an integer lead-time in hours to a bucket label."""
    if hours <= 12:
        return "0-12h"
    if hours <= 24:
        return "12-24h"
    if hours <= 48:
        return "24-48h"
    return "48h+"
