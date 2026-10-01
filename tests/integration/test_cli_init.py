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


def test_init_project_points_to_config_save(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--lang", "en"])

    assert "unskein config save" in result.output


def test_init_user_does_not_point_to_config_save() -> None:
    result = runner.invoke(app, ["init", "--user", "--lang", "en"])

    assert "config save" not in result.output


def test_config_save_copies_the_current_folder_config_to_the_user_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / PROJECT_CONFIG_NAME).write_text('[general]\nlang = "en"\n', encoding="utf-8")

    result = runner.invoke(app, ["config", "save", "--lang", "en"])

    assert result.exit_code == ExitCode.OK
    assert config.USER_CONFIG_PATH.read_text(encoding="utf-8") == '[general]\nlang = "en"\n'
    assert str(config.USER_CONFIG_PATH) in result.output


def test_config_save_takes_another_file(tmp_path: Path) -> None:
    source = tmp_path / "unskein.toml"
    source.write_text('[general]\nlang = "es"\n', encoding="utf-8")

    result = runner.invoke(app, ["config", "save", str(source)])

    assert result.exit_code == ExitCode.OK
    assert config.USER_CONFIG_PATH.read_text(encoding="utf-8") == '[general]\nlang = "es"\n'


def test_config_save_keeps_an_existing_user_config_without_force(tmp_path: Path) -> None:
    config.USER_CONFIG_PATH.write_text("[general]\n", encoding="utf-8")
    source = tmp_path / PROJECT_CONFIG_NAME
    source.write_text('[general]\nlang = "es"\n', encoding="utf-8")

    kept = runner.invoke(app, ["config", "save", str(source), "--lang", "en"])
    forced = runner.invoke(app, ["config", "save", str(source), "--force"])

    assert kept.exit_code == ExitCode.USAGE_ERROR
    assert "--force" in kept.output
    assert forced.exit_code == ExitCode.OK
    assert config.USER_CONFIG_PATH.read_text(encoding="utf-8") == '[general]\nlang = "es"\n'


def test_config_save_rejects_an_invalid_file(tmp_path: Path) -> None:
    source = tmp_path / PROJECT_CONFIG_NAME
    source.write_text("[ai]\nmodle = 'x'\n", encoding="utf-8")

    result = runner.invoke(app, ["config", "save", str(source), "--lang", "en"])

    assert result.exit_code == ExitCode.USAGE_ERROR
    assert str(source) in result.output
    assert not config.USER_CONFIG_PATH.exists()


def test_config_save_rejects_a_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", "save", str(tmp_path / "nope.toml"), "--lang", "en"])

    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "nope.toml" in result.output


def test_config_save_warns_about_a_key_in_the_file_without_showing_it(tmp_path: Path) -> None:
    secret = "sk-test-secret-value"
    source = tmp_path / PROJECT_CONFIG_NAME
    source.write_text(f'[ai]\nmodel = "gpt-4o-mini"\napi_key = "{secret}"\n', encoding="utf-8")

    result = runner.invoke(app, ["config", "save", str(source), "--lang", "en"])

    assert result.exit_code == ExitCode.OK
    assert "UNSKEIN_API_KEY" in result.output
    assert secret not in result.output
