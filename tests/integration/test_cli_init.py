from pathlib import Path

import pytest
from typer.testing import CliRunner

from unskein import config
from unskein.cli import app
from unskein.config import PROJECT_CONFIG_NAME
from unskein.errors import ExitCode
from unskein.init_config import config_template

runner = CliRunner()


def test_init_writes_the_template_in_the_given_folder(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--lang", "en"])

    target = tmp_path / PROJECT_CONFIG_NAME
    assert result.exit_code == ExitCode.OK
    assert target.read_text(encoding="utf-8") == config_template()
    assert str(target) in result.output


def test_init_defaults_to_the_current_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["init"])

    assert result.exit_code == ExitCode.OK
    assert (tmp_path / PROJECT_CONFIG_NAME).is_file()


def test_init_keeps_an_existing_file_and_exits_with_usage_error(tmp_path: Path) -> None:
    target = tmp_path / PROJECT_CONFIG_NAME
    target.write_text("[general]\n", encoding="utf-8")

    result = runner.invoke(app, ["init", str(tmp_path), "--lang", "es"])

    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "--force" in result.output
    assert target.read_text(encoding="utf-8") == "[general]\n"


def test_init_force_overwrites(tmp_path: Path) -> None:
    target = tmp_path / PROJECT_CONFIG_NAME
    target.write_text("[general]\n", encoding="utf-8")

    result = runner.invoke(app, ["init", str(tmp_path), "--force"])

    assert result.exit_code == ExitCode.OK
    assert target.read_text(encoding="utf-8") == config_template()


def test_init_user_writes_the_user_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "--user"])

    assert result.exit_code == ExitCode.OK
    assert config.USER_CONFIG_PATH.read_text(encoding="utf-8") == config_template()
    assert not (tmp_path / PROJECT_CONFIG_NAME).exists()


def test_init_rejects_a_path_that_is_not_a_folder(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path / "missing"), "--lang", "en"])

    assert result.exit_code == ExitCode.USAGE_ERROR
    assert not (tmp_path / "missing").exists()
