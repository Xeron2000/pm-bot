from __future__ import annotations

from unittest.mock import patch

import typer


class TestMainModule:
    def test_app_is_typer(self):
        with patch("sys.argv", ["pm-bot", "--help"]):
            from pm_bot.cli.app import app
            assert isinstance(app, typer.Typer)

    def test_main_module_file_exists(self):
        from pathlib import Path
        main_path = Path(__file__).parent.parent / "pm_bot" / "__main__.py"
        assert main_path.exists()
        content = main_path.read_text()
        assert "app()" in content

    def test_main_module_invocation(self):
        from pm_bot import __main__ as m
        assert hasattr(m, "app")
