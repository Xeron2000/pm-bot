"""City Variance Filtering — skip high-volatility cities.

Tracks historical forecast error (predicted vs observed) per city.
Cities with high MAE or error std are flagged as high-variance.

Usage:
    from pm_bot.core.city_variance import CityVarianceDB, is_tradeable

    db = CityVarianceDB()
    if not db.is_tradeable("Chicago", max_mae=3.0):
        continue  # skip high-variance city
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import structlog

from pm_bot.core.db import DEFAULT_DB_PATH

log = structlog.get_logger()

VARIANCE_DB_PATH = Path.home() / ".pm-bot" / "city_variance.db"

# Minimum observations before variance score is reliable
MIN_OBSERVATIONS = 10

# Default thresholds
DEFAULT_MAX_MAE = 3.5  # °C — skip cities with MAE > this
DEFAULT_MAX_STD = 4.0  # °C — skip cities with error std > this

# Pre-computed tier overrides (from research + backtest)
# These are used as priors before enough data is collected
CITY_TIER_PRIORS: dict[str, str] = {
    # Tier 1 — Low variance (stable climate, good forecast accuracy)
    "Miami": "low",
    "Los Angeles": "low",
    "San Francisco": "low",
    "Hong Kong": "low",
    "Jeddah": "low",
    "Lagos": "low",
    "Jakarta": "low",
    # Tier 2 — Medium variance
    "NYC": "medium",
    "New York": "medium",
    "London": "medium",
    "Tokyo": "medium",
    "Paris": "medium",
    "Madrid": "medium",
    "Taipei": "medium",
    "Seoul": "medium",
    "Beijing": "medium",
    "Shanghai": "medium",
    "Warsaw": "medium",
    "Milan": "medium",
    "Munich": "medium",
    "Amsterdam": "medium",
    "Busan": "medium",
    "Helsinki": "medium",
    "Moscow": "medium",
    "Toronto": "medium",
    "Wellington": "medium",
    "Denver": "medium",
    "Austin": "medium",
    "Atlanta": "medium",
    "Dallas": "medium",
    "Seattle": "medium",
    "São Paulo": "medium",
    "Mexico City": "medium",
    "Cape Town": "medium",
    "Buenos Aires": "medium",
    "Istanbul": "medium",
    "Wuhan": "medium",
    "Ankara": "medium",
    # Tier 3 — High variance (transitional seasons, volatile climate)
    "Chicago": "high",  # spring temp swings
}

# Tier thresholds
TIER_MAE_THRESHOLDS: dict[str, float] = {
    "low": 2.0,    # MAE < 2.0°C
    "medium": 3.5,  # MAE 2.0-3.5°C
    "high": 999.0,  # MAE > 3.5°C
}


@dataclass
class CityVarianceEntry:
    """Per-city forecast error statistics."""

    city: str
    sample_count: int = 0
    sum_error: float = 0.0
    sum_abs_error: float = 0.0
    sum_sq_error: float = 0.0
    last_updated: str = ""

    @property
    def mae(self) -> float:
        """Mean Absolute Error."""
        if self.sample_count == 0:
            return 0.0
        return self.sum_abs_error / self.sample_count

    @property
    def mean_error(self) -> float:
        """Mean signed error (bias)."""
        if self.sample_count == 0:
            return 0.0
        return self.sum_error / self.sample_count

    @property
    def std(self) -> float:
        """Standard deviation of errors."""
        if self.sample_count < 2:
            return 0.0
        mean = self.mean_error
        variance = (self.sum_sq_error / self.sample_count) - mean**2
        return math.sqrt(max(0.0, variance))

    @property
    def tier(self) -> str:
        """Classify into tier based on MAE."""
        if self.sample_count < MIN_OBSERVATIONS:
            return "unknown"
        mae = self.mae
        if mae < TIER_MAE_THRESHOLDS["low"]:
            return "low"
        if mae < TIER_MAE_THRESHOLDS["medium"]:
            return "medium"
        return "high"

    def update(self, predicted_c: float, observed_c: float) -> None:
        """Update statistics with a new forecast-observation pair."""
        error = observed_c - predicted_c
        self.sum_error += error
        self.sum_abs_error += abs(error)
        self.sum_sq_error += error**2
        self.sample_count += 1
        self.last_updated = datetime.now(timezone.utc).isoformat()


class CityVarianceDB:
    """Persistent storage for city variance statistics.

    Args:
        db_path: Path to SQLite database. Defaults to ~/.pm-bot/city_variance.db.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or VARIANCE_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._entries: dict[str, CityVarianceEntry] = {}
        self._loaded = False

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS city_variance (
                city TEXT PRIMARY KEY,
                sample_count INTEGER NOT NULL DEFAULT 0,
                sum_error REAL NOT NULL DEFAULT 0.0,
                sum_abs_error REAL NOT NULL DEFAULT 0.0,
                sum_sq_error REAL NOT NULL DEFAULT 0.0,
                last_updated TEXT
            )
        """)
        self._conn.commit()
        return self._conn

    def _load(self) -> None:
        """Load all entries from database."""
        if self._loaded:
            return
        conn = self._get_conn()
        for row in conn.execute("SELECT * FROM city_variance"):
            self._entries[row["city"]] = CityVarianceEntry(
                city=row["city"],
                sample_count=row["sample_count"],
                sum_error=row["sum_error"],
                sum_abs_error=row["sum_abs_error"],
                sum_sq_error=row["sum_sq_error"],
                last_updated=row["last_updated"] or "",
            )
        self._loaded = True

    def _save_entry(self, entry: CityVarianceEntry) -> None:
        """Persist a single entry to database."""
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO city_variance
               (city, sample_count, sum_error, sum_abs_error, sum_sq_error, last_updated)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                entry.city,
                entry.sample_count,
                entry.sum_error,
                entry.sum_abs_error,
                entry.sum_sq_error,
                entry.last_updated,
            ),
        )
        conn.commit()

    def record(self, city: str, predicted_c: float, observed_c: float) -> None:
        """Record a forecast-observation pair for a city.

        Args:
            city: City name (canonical form, not alias).
            predicted_c: Predicted temperature in °C.
            observed_c: Observed temperature in °C.
        """
        self._load()
        if city not in self._entries:
            self._entries[city] = CityVarianceEntry(city=city)
        entry = self._entries[city]
        entry.update(predicted_c, observed_c)
        self._save_entry(entry)

    def get_entry(self, city: str) -> CityVarianceEntry | None:
        """Get variance entry for a city."""
        self._load()
        return self._entries.get(city)

    def get_mae(self, city: str) -> float | None:
        """Get MAE for a city. Returns None if insufficient data."""
        entry = self.get_entry(city)
        if entry is None or entry.sample_count < MIN_OBSERVATIONS:
            return None
        return entry.mae

    def get_tier(self, city: str) -> str:
        """Get variance tier for a city.

        Returns:
            "low", "medium", "high", or "unknown" (insufficient data).
            Falls back to CITY_TIER_PRIORS if no data.
        """
        entry = self.get_entry(city)
        if entry is not None and entry.sample_count >= MIN_OBSERVATIONS:
            return entry.tier
        # Fall back to prior
        return CITY_TIER_PRIORS.get(city, "unknown")

    def is_tradeable(
        self,
        city: str,
        max_mae: float = DEFAULT_MAX_MAE,
        max_std: float = DEFAULT_MAX_STD,
        allowed_tiers: Sequence[str] | None = None,
    ) -> bool:
        """Check if a city passes variance filters.

        Args:
            city: City name.
            max_mae: Maximum allowed MAE (°C).
            max_std: Maximum allowed error std (°C).
            allowed_tiers: If set, only these tiers are tradeable.

        Returns:
            True if city passes all filters.
        """
        tier = self.get_tier(city)

        # If allowed_tiers specified, check tier first
        if allowed_tiers is not None and tier not in allowed_tiers:
            return False

        # If we have data, check MAE and std
        entry = self.get_entry(city)
        if entry is not None and entry.sample_count >= MIN_OBSERVATIONS:
            if entry.mae > max_mae:
                return False
            if entry.std > max_std:
                return False

        return True

    def get_all_scores(self) -> list[dict]:
        """Return variance scores for all cities with data.

        Returns:
            List of dicts with city, mae, std, tier, sample_count.
        """
        self._load()
        results = []
        for city, entry in sorted(self._entries.items()):
            results.append({
                "city": city,
                "mae": round(entry.mae, 2),
                "mean_error": round(entry.mean_error, 2),
                "std": round(entry.std, 2),
                "tier": entry.tier,
                "samples": entry.sample_count,
                "prior_tier": CITY_TIER_PRIORS.get(city, "unknown"),
            })
        return results

    def get_tradeable_cities(
        self,
        max_mae: float = DEFAULT_MAX_MAE,
        max_std: float = DEFAULT_MAX_STD,
        allowed_tiers: Sequence[str] | None = None,
    ) -> list[str]:
        """Return list of cities that pass variance filters."""
        from pm_bot.models.config import DEFAULT_CITIES

        return [c for c in DEFAULT_CITIES if self.is_tradeable(c, max_mae, max_std, allowed_tiers)]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# Singleton for convenience
_default_db: CityVarianceDB | None = None


def get_default_db() -> CityVarianceDB:
    """Get or create singleton CityVarianceDB."""
    global _default_db
    if _default_db is None:
        _default_db = CityVarianceDB()
    return _default_db


def is_tradeable(city: str, **kwargs) -> bool:
    """Convenience function: check if city is tradeable using default DB."""
    return get_default_db().is_tradeable(city, **kwargs)


def get_tier(city: str) -> str:
    """Convenience function: get city tier using default DB."""
    return get_default_db().get_tier(city)


def filter_recommendations(
    recs: list,
    max_mae: float = DEFAULT_MAX_MAE,
    max_std: float = DEFAULT_MAX_STD,
    allowed_tiers: Sequence[str] | None = None,
) -> list:
    """Filter recommendations by city variance.

    Args:
        recs: List of Recommendation objects.
        max_mae: Maximum allowed MAE.
        max_std: Maximum allowed error std.
        allowed_tiers: If set, only these tiers pass.

    Returns:
        Filtered list with reasoning updated for removed items.
    """
    from pm_bot.models.market import Recommendation
    from pm_bot.models.config import resolve_city_alias

    db = get_default_db()
    result = []
    removed = []

    for rec in recs:
        city = resolve_city_alias(rec.event.city)
        if db.is_tradeable(city, max_mae, max_std, allowed_tiers):
            result.append(rec)
        else:
            tier = db.get_tier(city)
            entry = db.get_entry(city)
            mae_str = f"MAE={entry.mae:.1f}°C" if entry else "no data"
            removed.append(f"{city}({tier},{mae_str})")

    if removed:
        log.info("city_variance_filtered", removed=removed, kept=len(result))

    return result
