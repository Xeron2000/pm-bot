from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pm_bot.core.config_loader import (
    find_config_path,
    load_config,
    get_clob_creds,
    get_private_key,
    get_sizing,
    get_strategy_params,
    get_stations,
    get_notifications,
    get_station_for_city,
)


class TestFindConfigPath:
    def test_env_override(self):
        with patch.dict("os.environ", {"PM_BOT_CONFIG": "/custom/path.toml"}):
            result = find_config_path()
        assert str(result) == "/custom/path.toml"

    def test_default_path(self):
        with patch.dict("os.environ", {}, clear=True):
            result = find_config_path()
        assert result.name == "config.toml"


class TestLoadConfig:
    def test_missing_file_returns_empty(self):
        result = load_config(Path("/nonexistent/path.toml"))
        assert result == {}

    def test_load_existing(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False, mode="wb") as f:
            f.write(b'[sizing]\nmax_single = 10.0\n')
            tmppath = Path(f.name)
        try:
            result = load_config(tmppath)
            assert result["sizing"]["max_single"] == 10.0
        finally:
            tmppath.unlink(missing_ok=True)


class TestGetClobCreds:
    def test_from_env(self):
        with patch.dict("os.environ", {"CLOB_API_KEY": "env_key", "CLOB_SECRET": "env_sec", "CLOB_PASS_PHRASE": "env_ph"}):
            result = get_clob_creds({})
        assert result["api_key"] == "env_key"
        assert result["api_secret"] == "env_sec"

    def test_from_config(self):
        config = {"clob": {"api_key": "cfg_key", "api_secret": "cfg_sec", "api_passphrase": "cfg_ph"}}
        with patch.dict("os.environ", {}, clear=True):
            result = get_clob_creds(config)
        assert result["api_key"] == "cfg_key"


class TestGetPrivateKey:
    def test_from_env(self):
        with patch.dict("os.environ", {"POLY_PK": "0xabc"}):
            result = get_private_key()
        assert result == "0xabc"

    def test_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            result = get_private_key()
        assert result == ""


class TestGetSizing:
    def test_defaults(self):
        with patch.dict("os.environ", {}, clear=True):
            result = get_sizing({})
        assert result["max_single"] == 5.0
        assert result["max_daily"] == 50.0

    def test_from_config(self):
        config = {"sizing": {"max_single": 10.0, "max_daily": 100.0}}
        with patch.dict("os.environ", {}, clear=True):
            result = get_sizing(config)
        assert result["max_single"] == 10.0

    def test_env_override(self):
        with patch.dict("os.environ", {"PM_BOT_MAX_SINGLE": "20.0"}, clear=False):
            result = get_sizing({})
        assert result["max_single"] == 20.0


class TestGetStrategyParams:
    def test_existing(self):
        config = {"strategies": {"gopfan2": {"yes_max": 0.2}}}
        result = get_strategy_params(config, "gopfan2")
        assert result["yes_max"] == 0.2

    def test_missing(self):
        result = get_strategy_params({}, "nonexistent")
        assert result == {}


class TestGetStations:
    def test_with_stations(self):
        config = {"stations": {"KLGA": {"city": "New York"}}}
        result = get_stations(config)
        assert "KLGA" in result

    def test_empty(self):
        result = get_stations({})
        assert result == {}


class TestGetNotifications:
    def test_with_notifications(self):
        config = {"notifications": {"slack": "hook"}}
        result = get_notifications(config)
        assert "slack" in result

    def test_empty(self):
        result = get_notifications({})
        assert result == {}


class TestGetStationForCity:
    def test_match(self):
        config = {"stations": {"KLGA": {"city": "New York", "lat": 40.7}}}
        result = get_station_for_city(config, "New York")
        assert result is not None
        assert result["icao"] == "KLGA"

    def test_no_match(self):
        result = get_station_for_city({"stations": {}}, "London")
        assert result is None
