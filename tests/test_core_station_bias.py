from __future__ import annotations

import tempfile
from pathlib import Path

from pm_bot.core.station_bias import (
    STATION_PRIORS,
    StationBiasDB,
    StationBiasEntry,
    _lead_time_bucket,
    DEFAULT_ALPHA,
    WARMUP_DAYS,
)


class TestLeadTimeBucket:
    def test_short(self):
        assert _lead_time_bucket(6) == "0-12h"

    def test_medium(self):
        assert _lead_time_bucket(18) == "12-24h"

    def test_long(self):
        assert _lead_time_bucket(36) == "24-48h"

    def test_very_long(self):
        assert _lead_time_bucket(72) == "48h+"


class TestStationBiasEntry:
    def test_initial_values(self):
        entry = StationBiasEntry(station="KLGA", lead_time_bucket="12-24h")
        assert entry.bias_c == 0.0
        assert entry.sample_count == 0

    def test_update_increments_count(self):
        entry = StationBiasEntry(station="KLGA", lead_time_bucket="12-24h")
        entry.update(observed_c=25.0, predicted_c=24.0)
        assert entry.sample_count == 1
        assert entry.bias_c > 0

    def test_update_ema_convergence(self):
        entry = StationBiasEntry(station="KLGA", lead_time_bucket="12-24h")
        for _ in range(100):
            entry.update(observed_c=25.0, predicted_c=24.0, alpha=0.3)
        assert abs(entry.bias_c - 1.0) < 0.1

    def test_update_negative_bias(self):
        entry = StationBiasEntry(station="KLGA", lead_time_bucket="12-24h")
        entry.update(observed_c=23.0, predicted_c=25.0)
        assert entry.bias_c < 0


class TestStationBiasDB:
    def test_empty_db(self):
        db = StationBiasDB()
        assert db.get_bias("KLGA") == 0.0

    def test_record_and_get(self):
        db = StationBiasDB()
        for _ in range(WARMUP_DAYS + 1):
            db.record("KLGA", observed_c=25.0, predicted_c=24.0)
        bias = db.get_bias("KLGA")
        assert bias > 0

    def test_below_warmup_returns_prior_or_zero(self):
        db = StationBiasDB()
        for _ in range(WARMUP_DAYS - 1):
            db.record("KLGA", observed_c=25.0, predicted_c=24.0)
        # KLGA is not in STATION_PRIORS, so 0.0 fallback
        assert db.get_bias("KLGA") == 0.0

    def test_apply_correction(self):
        db = StationBiasDB()
        for _ in range(WARMUP_DAYS + 1):
            db.record("KLGA", observed_c=26.0, predicted_c=25.0)
        corrected = db.apply_correction(25.0, "KLGA")
        assert corrected > 25.0

    def test_save_and_load(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)

        try:
            db = StationBiasDB()
            for _ in range(WARMUP_DAYS + 1):
                db.record("KLGA", observed_c=25.0, predicted_c=24.0)
            db.save(path)

            loaded = StationBiasDB.load(path)
            assert abs(loaded.get_bias("KLGA") - db.get_bias("KLGA")) < 0.001
        finally:
            path.unlink(missing_ok=True)

    def test_load_nonexistent(self):
        db = StationBiasDB.load(Path("/tmp/nonexistent_bias_test.json"))
        assert len(db.entries) == 0

    def test_load_corrupt_file(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("not valid json{{{")
            path = Path(f.name)

        try:
            db = StationBiasDB.load(path)
            assert len(db.entries) == 0
        finally:
            path.unlink(missing_ok=True)

    def test_different_lead_times(self):
        db = StationBiasDB()
        for _ in range(WARMUP_DAYS + 1):
            db.record("KLGA", observed_c=25.0, predicted_c=24.0, lead_time_hours=12)
        for _ in range(WARMUP_DAYS + 1):
            db.record("KLGA", observed_c=25.0, predicted_c=23.0, lead_time_hours=24)
        bias_12 = db.get_bias("KLGA", lead_time_hours=12)
        bias_24 = db.get_bias("KLGA", lead_time_hours=24)
        assert bias_12 != bias_24

    def test_alpha_default(self):
        assert DEFAULT_ALPHA == 0.15

    def test_warmup_days(self):
        assert WARMUP_DAYS == 30

    def test_below_warmup_returns_prior_for_known_station(self):
        db = StationBiasDB()
        for _ in range(3):
            db.record("New York", observed_c=25.0, predicted_c=24.0)
        assert db.get_bias("New York") == 0.7

    def test_below_warmup_returns_zero_for_unknown_station(self):
        db = StationBiasDB()
        for _ in range(3):
            db.record("KLGA", observed_c=25.0, predicted_c=24.0)
        assert db.get_bias("KLGA") == 0.0

    def test_prior_overridden_after_warmup(self):
        db = StationBiasDB()
        for _ in range(WARMUP_DAYS + 1):
            db.record("New York", observed_c=25.0, predicted_c=20.0)
        # After warmup, EMA bias should dominate over prior
        assert db.get_bias("New York") > 1.0

    def test_station_priors_values(self):
        assert STATION_PRIORS["New York"] == 0.7
        assert STATION_PRIORS["London"] == 0.8
        assert STATION_PRIORS["Hong Kong"] == 0.5
        assert STATION_PRIORS["Miami"] == 0.6
        assert STATION_PRIORS["Dallas"] == 1.1
        assert STATION_PRIORS["Seoul"] == 0.9
        assert STATION_PRIORS["Tokyo"] == 0.8
        assert STATION_PRIORS["Shanghai"] == 0.9
        assert STATION_PRIORS["Beijing"] == 0.9
        assert STATION_PRIORS["Paris"] == 0.7
