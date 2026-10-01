import re
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
    load_toml_config,
)
from unskein.errors import ErrorKey, UnskeinError
from unskein.init_config import config_template, write_config

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
