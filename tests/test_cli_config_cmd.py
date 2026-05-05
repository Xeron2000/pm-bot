from __future__ import annotations

from unittest.mock import patch
from pathlib import Path

from pm_bot.cli.config_cmd import run_config, _run_config_init


class TestRunConfig:
    @patch("pm_bot.cli.config_cmd.load_config", return_value={})
    @patch("pm_bot.cli.config_cmd.find_config_path", return_value=Path("/tmp/test_config.toml"))
    def test_show_config(self, mock_find, mock_load):
        run_config(init=False)

    @patch("pm_bot.cli.config_cmd.load_config", return_value={"sizing": {"max_single": 10.0, "max_daily": 100.0}})
    @patch("pm_bot.cli.config_cmd.find_config_path", return_value=Path("/tmp/test_config.toml"))
    def test_show_config_with_sizing(self, mock_find, mock_load):
        run_config(init=False)

    @patch("pm_bot.cli.config_cmd.load_config", return_value={"clob": {"api_key": "test_key"}})
    @patch("pm_bot.cli.config_cmd.find_config_path", return_value=Path("/tmp/test_config.toml"))
    def test_show_config_with_creds(self, mock_find, mock_load):
        run_config(init=False)

    @patch("pm_bot.cli.config_cmd.load_config", return_value={"notifications": {"discord": {"webhook_url": "https://example.com"}, "telegram": {"bot_token": "tok"}}})
    @patch("pm_bot.cli.config_cmd.find_config_path", return_value=Path("/tmp/test_config.toml"))
    def test_show_config_with_notifications(self, mock_find, mock_load):
        run_config(init=False)

    @patch("pm_bot.cli.config_cmd.load_config", return_value={})
    @patch("pm_bot.cli.config_cmd.find_config_path", return_value=Path("/tmp/test_config.toml"))
    def test_show_config_with_poly_pk(self, mock_find, mock_load):
        with patch.dict("os.environ", {"POLY_PK": "0xtest"}):
            run_config(init=False)


class TestRunConfigInit:
    @patch("pm_bot.cli.config_cmd.find_config_path", return_value=Path("/tmp/test_config.toml"))
    def test_existing_config(self, mock_find):
        with patch.object(Path, "exists", return_value=True):
            _run_config_init()

    @patch("pm_bot.cli.config_cmd.find_config_path", return_value=Path("/tmp/test_config_new.toml"))
    def test_no_example(self, mock_find):
        with patch.object(Path, "exists", return_value=False):
            _run_config_init()
