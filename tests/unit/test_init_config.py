import os
import re
import stat
import sys
import tomllib
from dataclasses import fields
from pathlib import Path

import pytest

from unskein.config import (
    PROJECT_CONFIG_NAME,
    AnalysisConfig,
    FindingsConfig,
    TomlAI,
    TomlAnalysis,
    TomlConfig,
    TomlFindings,
    TomlGeneral,
    TomlLayers,
    load_toml_config,
)
from unskein.errors import ConfigError, ErrorKey, UnskeinError
from unskein.init_config import config_template, save_user_config, write_config

COMMENTED_SETTING = re.compile(r"^# (\w+ = .*)$", flags=re.MULTILINE)


def uncommented_template() -> dict:
    """Parse the template with every commented-out setting switched on.

    Returns:
        The template's tables, as a user who uncommented every line would have them.
    """
    return tomllib.loads(COMMENTED_SETTING.sub(r"\1", config_template()))


def test_template_as_generated_changes_nothing(tmp_path: Path) -> None:
    (tmp_path / PROJECT_CONFIG_NAME).write_text(config_template(), encoding="utf-8")

    assert load_toml_config(tmp_path) == TomlConfig()


@pytest.mark.parametrize(
    ("table", "schema"),
    [
        ("general", TomlGeneral),
        ("ai", TomlAI),
        ("analysis", TomlAnalysis),
        ("findings", TomlFindings),
        ("layers", TomlLayers),
    ],
)
def test_template_documents_every_setting(table: str, schema: type) -> None:
    assert set(uncommented_template()[table]) == set(schema.model_fields)


def test_uncommented_template_is_a_valid_config() -> None:
    TomlConfig.model_validate(uncommented_template())


def test_template_shows_the_real_analysis_defaults() -> None:
    documented = uncommented_template()["analysis"]
    defaults = AnalysisConfig()

    for field in fields(AnalysisConfig):
        default = getattr(defaults, field.name)
        if field.name in documented and default is not None:
            assert documented[field.name] == default, field.name


def test_template_shows_the_real_findings_defaults() -> None:
    documented = uncommented_template()["findings"]
    defaults = FindingsConfig()

    for field in fields(FindingsConfig):
        default = getattr(defaults, field.name)
        if field.name in documented and default is not None and field.name != "entry_points":
            assert documented[field.name] == default, field.name


def test_write_config_creates_the_template_and_its_folder(tmp_path: Path) -> None:
    target = tmp_path / "home" / ".config" / "unskein" / "config.toml"

    write_config(target)

    assert target.read_text(encoding="utf-8") == config_template()


def test_write_config_refuses_to_overwrite(tmp_path: Path) -> None:
    target = tmp_path / PROJECT_CONFIG_NAME
    target.write_text("[general]\n", encoding="utf-8")

    with pytest.raises(UnskeinError) as raised:
        write_config(target)

    assert raised.value.key == ErrorKey.CONFIG_EXISTS
    assert raised.value.params == {"path": str(target)}
    assert target.read_text(encoding="utf-8") == "[general]\n"


def test_write_config_overwrites_when_forced(tmp_path: Path) -> None:
    target = tmp_path / PROJECT_CONFIG_NAME
    target.write_text("[general]\n", encoding="utf-8")

    write_config(target, force=True)

    assert target.read_text(encoding="utf-8") == config_template()


PROJECT_CONFIG = (
    '# my settings\n[general]\nlang = "es"\n\n[ai]\nmodel = "litellm_proxy/Some Alias"\n'
)
SECRET = "sk-test-secret-value"


def project_config(tmp_path: Path, text: str = PROJECT_CONFIG) -> Path:
    """Write a project config file and return its path.

    Args:
        tmp_path: Pytest temporary directory.
        text: File contents.

    Returns:
        The written ``.unskein.toml``.
    """
    source = tmp_path / PROJECT_CONFIG_NAME
    source.write_text(text, encoding="utf-8")
    return source


def test_save_user_config_copies_the_file_verbatim_and_creates_its_folder(
    tmp_path: Path,
) -> None:
    target = tmp_path / "home" / ".config" / "unskein" / "config.toml"

    saved = save_user_config(project_config(tmp_path), target)

    assert target.read_text(encoding="utf-8") == PROJECT_CONFIG
    assert saved.ai.model == "litellm_proxy/Some Alias"


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("[general\n", ErrorKey.INVALID_TOML),
        ("[ai]\nmodle = 'x'\n", ErrorKey.UNKNOWN_KEY),
        ("[general]\nlang = 3\n", ErrorKey.INVALID_VALUE),
    ],
)
def test_save_user_config_rejects_an_invalid_file_without_writing(
    tmp_path: Path, text: str, key: ErrorKey
) -> None:
    target = tmp_path / "home" / "config.toml"

    with pytest.raises(ConfigError) as raised:
        save_user_config(project_config(tmp_path, text), target)

    assert raised.value.key == key
    assert not target.parent.exists()


def test_save_user_config_needs_an_existing_file(tmp_path: Path) -> None:
    source = tmp_path / "missing.toml"

    with pytest.raises(UnskeinError) as raised:
        save_user_config(source, tmp_path / "config.toml")

    assert raised.value.key == ErrorKey.CONFIG_NOT_FOUND
    assert raised.value.params == {"path": str(source)}


def test_save_user_config_refuses_to_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text("[general]\n", encoding="utf-8")

    with pytest.raises(UnskeinError) as raised:
        save_user_config(project_config(tmp_path), target)

    assert raised.value.key == ErrorKey.CONFIG_EXISTS
    assert target.read_text(encoding="utf-8") == "[general]\n"


def test_save_user_config_overwrites_when_forced(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text("[general]\n", encoding="utf-8")

    save_user_config(project_config(tmp_path), target, force=True)

    assert target.read_text(encoding="utf-8") == PROJECT_CONFIG


def test_save_user_config_reports_a_key_written_in_the_file(tmp_path: Path) -> None:
    text = f'[ai]\nmodel = "gpt-4o-mini"\napi_key = "{SECRET}"\n'

    saved = save_user_config(project_config(tmp_path, text), tmp_path / "config.toml")

    assert saved.ai.api_key == SECRET


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_save_user_config_keeps_the_file_private(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text("[general]\n", encoding="utf-8")
    os.chmod(target, 0o644)

    save_user_config(project_config(tmp_path), target, force=True)

    assert stat.S_IMODE(target.stat().st_mode) == 0o600
