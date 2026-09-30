import pytest
from typer.testing import CliRunner

from unskein import __version__
from unskein.cli import app
from unskein.errors import ExitCode
from unskein.guide import usage_guide
from unskein.i18n import Lang

runner = CliRunner()


def test_guide_prints_the_spanish_guide(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNSKEIN_LANG", "en")

    result = runner.invoke(app, ["guide", "--lang", "es"])

    assert result.exit_code == ExitCode.OK
    assert f"unskein {__version__} — guía de uso" in result.output


def test_guide_language_follows_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNSKEIN_LANG", "en")

    result = runner.invoke(app, ["guide"])

    assert f"unskein {__version__} — usage guide" in result.output


def test_guide_piped_is_the_raw_markdown() -> None:
    result = runner.invoke(app, ["guide", "--lang", "en"])

    assert result.output == usage_guide(Lang.EN)
