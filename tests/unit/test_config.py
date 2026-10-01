from pathlib import Path

import pytest

from unskein.config import (
    AnalysisConfig,
    AnalysisFlags,
    FindingsConfig,
    TomlAI,
    TomlAnalysis,
    TomlConfig,
    load_toml_config,
    resolve_ai_config,
    resolve_analysis_config,
    resolve_findings_config,
)
from unskein.errors import ConfigError, ErrorKey


def write(path: Path, text: str) -> Path:
    """Write a TOML file, creating parent directories.

    Args:
        path: File to write.
        text: TOML content.

    Returns:
        The written path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_files_give_empty_config(tmp_path: Path) -> None:
    config = load_toml_config(tmp_path, user_config=tmp_path / "nope.toml")
    assert config.analysis.include_tests is None
    assert config.ai.model is None
    assert config.general.lang is None


def test_project_file_wins_key_by_key_over_user_file(tmp_path: Path) -> None:
    user = write(
        tmp_path / "home/config.toml",
        '[ai]\nmodel = "ollama/a"\napi_base = "http://user"\n[analysis]\nparallel_threshold = 10\n',
    )
    write(tmp_path / ".unskein.toml", '[ai]\nmodel = "ollama/b"\n')
    config = load_toml_config(tmp_path, user_config=user)
    assert config.ai.model == "ollama/b"
    assert config.ai.api_base == "http://user"
    assert config.analysis.parallel_threshold == 10


def test_invalid_toml_names_the_file(tmp_path: Path) -> None:
    project = write(tmp_path / ".unskein.toml", "[analysis\n")
    with pytest.raises(ConfigError) as exc:
        load_toml_config(tmp_path, user_config=tmp_path / "nope.toml")
    assert exc.value.key == "invalid_toml"
    assert exc.value.params["file"] == str(project)


def test_unknown_key_is_rejected_with_file_and_field(tmp_path: Path) -> None:
    project = write(tmp_path / ".unskein.toml", "[analysis]\ninclude_test = true\n")
    with pytest.raises(ConfigError) as exc:
        load_toml_config(tmp_path, user_config=tmp_path / "nope.toml")
    assert exc.value.key == "unknown_key"
    assert exc.value.params == {"file": str(project), "field": "analysis.include_test"}


def test_unknown_table_is_rejected(tmp_path: Path) -> None:
    write(tmp_path / ".unskein.toml", "[analisis]\n")
    with pytest.raises(ConfigError) as exc:
        load_toml_config(tmp_path, user_config=tmp_path / "nope.toml")
    assert exc.value.key == "unknown_key"
    assert exc.value.params["field"] == "analisis"


def test_wrong_type_is_rejected_without_coercion(tmp_path: Path) -> None:
    write(tmp_path / ".unskein.toml", '[analysis]\nparallel_threshold = "50"\n')
    with pytest.raises(ConfigError) as exc:
        load_toml_config(tmp_path, user_config=tmp_path / "nope.toml")
    assert exc.value.key == "invalid_value"
    assert exc.value.params["field"] == "analysis.parallel_threshold"


def test_unsupported_lang_is_rejected(tmp_path: Path) -> None:
    write(tmp_path / ".unskein.toml", '[general]\nlang = "fr"\n')
    with pytest.raises(ConfigError) as exc:
        load_toml_config(tmp_path, user_config=tmp_path / "nope.toml")
    assert exc.value.params["field"] == "general.lang"


def test_invalid_api_key_value_never_appears_in_the_error(tmp_path: Path) -> None:
    write(tmp_path / ".unskein.toml", "[ai]\napi_key = 123456789\n")
    with pytest.raises(ConfigError) as exc:
        load_toml_config(tmp_path, user_config=tmp_path / "nope.toml")
    assert "123456789" not in f"{exc.value} {exc.value.params} {exc.value!r}"


def toml_analysis(**values: object) -> TomlConfig:
    """Build a TomlConfig whose ``[analysis]`` table has the given values.

    Args:
        **values: Keys of the ``[analysis]`` table.

    Returns:
        The config.
    """
    return TomlConfig(analysis=TomlAnalysis(**values))


def test_defaults_apply_when_nothing_is_set() -> None:
    assert resolve_analysis_config(TomlConfig(), AnalysisFlags()) == AnalysisConfig()


def test_toml_overrides_defaults() -> None:
    config = resolve_analysis_config(
        toml_analysis(parallel_threshold=10, source_roots=["lib"], default_encoding="latin-1"),
        AnalysisFlags(),
    )
    assert config.parallel_threshold == 10
    assert config.source_roots == ["lib"]
    assert config.default_encoding == "latin-1"


@pytest.mark.parametrize(
    ("toml_value", "flag", "expected"),
    [
        (None, None, False),
        (True, None, True),
        (True, False, False),
        (False, True, True),
        (None, True, True),
    ],
)
def test_boolean_flag_wins_in_both_directions(
    toml_value: bool | None, flag: bool | None, expected: bool
) -> None:
    config = resolve_analysis_config(
        toml_analysis(include_tests=toml_value, follow_symlinks=toml_value),
        AnalysisFlags(include_tests=flag, follow_symlinks=flag),
    )
    assert (config.include_tests, config.follow_symlinks) == (expected, expected)


def test_encoding_flag_wins_over_toml() -> None:
    config = resolve_analysis_config(
        toml_analysis(default_encoding="latin-1"), AnalysisFlags(encoding="cp1252")
    )
    assert config.default_encoding == "cp1252"


def test_excludes_from_toml_and_flags_are_combined() -> None:
    config = resolve_analysis_config(
        toml_analysis(exclude=["gen/**"]), AnalysisFlags(exclude=("migrations/**",))
    )
    assert config.exclude == ["gen/**", "migrations/**"]


def toml_ai(**values: str) -> TomlConfig:
    """Build a TomlConfig whose ``[ai]`` table has the given values.

    Args:
        **values: Keys of the ``[ai]`` table.

    Returns:
        The config.
    """
    return TomlConfig(ai=TomlAI(**values))


def test_no_model_in_any_layer_disables_ai() -> None:
    assert resolve_ai_config(toml_ai(api_key="k"), env={}, cli_api_key="k") is None


def test_env_model_and_base_win_over_toml() -> None:
    config = resolve_ai_config(
        toml_ai(model="ollama/a", api_base="http://toml"),
        env={"UNSKEIN_AI_MODEL": "ollama/b", "UNSKEIN_AI_API_BASE": "http://env"},
        cli_api_key=None,
    )
    assert (config.model, config.api_base) == ("ollama/b", "http://env")


@pytest.mark.parametrize(
    ("env_key", "toml_key", "flag_key", "expected"),
    [
        ("from-env", "from-toml", "from-flag", "from-env"),
        (None, "from-toml", "from-flag", "from-toml"),
        (None, None, "from-flag", "from-flag"),
        (None, None, None, None),
    ],
)
def test_api_key_precedence_is_env_then_toml_then_flag(
    env_key: str | None, toml_key: str | None, flag_key: str | None, expected: str | None
) -> None:
    env = {"UNSKEIN_API_KEY": env_key} if env_key else {}
    toml = TomlConfig(ai=TomlAI(model="m", api_key=toml_key))
    assert resolve_ai_config(toml, env=env, cli_api_key=flag_key).api_key == expected


def test_api_key_is_not_in_repr() -> None:
    config = resolve_ai_config(toml_ai(model="m", api_key="s3cr3t-value"), env={}, cli_api_key=None)
    assert "s3cr3t-value" not in repr(config)


def test_api_key_is_not_in_loaded_toml_repr() -> None:
    assert "s3cr3t-value" not in repr(toml_ai(model="m", api_key="s3cr3t-value"))


def test_findings_defaults_when_nothing_is_configured() -> None:
    assert resolve_findings_config(TomlConfig(), None) == FindingsConfig()


def test_findings_toml_overrides_the_defaults(tmp_path: Path) -> None:
    write(
        tmp_path / ".unskein.toml",
        '[findings]\nbottleneck_percentile = 80\nstability_gap = 0.4\nentry_points = ["app.cli"]\n',
    )
    toml = load_toml_config(tmp_path, user_config=tmp_path / "nope.toml")

    config = resolve_findings_config(toml, None)

    assert (config.bottleneck_percentile, config.stability_gap) == (80, 0.4)
    assert config.entry_points == ("app.cli",)


@pytest.mark.parametrize(
    ("in_toml", "flag", "expected"), [(True, False, False), (False, True, True)]
)
def test_findings_flag_beats_the_toml(
    tmp_path: Path, in_toml: bool, flag: bool, expected: bool
) -> None:
    write(tmp_path / ".unskein.toml", f"[findings]\nenabled = {str(in_toml).lower()}\n")
    toml = load_toml_config(tmp_path, user_config=tmp_path / "nope.toml")

    assert resolve_findings_config(toml, flag).enabled is expected


def test_script_entry_points_come_before_the_configured_ones(tmp_path: Path) -> None:
    write(tmp_path / ".unskein.toml", '[findings]\nentry_points = ["app.cli"]\n')
    toml = load_toml_config(tmp_path, user_config=tmp_path / "nope.toml")

    config = resolve_findings_config(toml, None, ("pkg.main",))

    assert config.entry_points == ("pkg.main", "app.cli")


@pytest.mark.parametrize(
    "line",
    [
        "bottleneck_percentile = 0",
        "bottleneck_percentile = 101",
        "orchestrator_percentile = 101",
        "stability_gap = 1.5",
        "orchestrator_min_efferent = -1",
    ],
)
def test_findings_value_out_of_range_is_a_config_error(tmp_path: Path, line: str) -> None:
    write(tmp_path / ".unskein.toml", f"[findings]\n{line}\n")

    with pytest.raises(ConfigError) as raised:
        load_toml_config(tmp_path, user_config=tmp_path / "nope.toml")

    assert raised.value.key == ErrorKey.INVALID_VALUE


def test_unknown_findings_key_is_a_config_error(tmp_path: Path) -> None:
    write(tmp_path / ".unskein.toml", "[findings]\nbottleneck = 3\n")

    with pytest.raises(ConfigError) as raised:
        load_toml_config(tmp_path, user_config=tmp_path / "nope.toml")

    assert raised.value.key == ErrorKey.UNKNOWN_KEY


def test_package_depth_defaults_to_automatic() -> None:
    assert FindingsConfig().package_depth is None


def test_package_depth_comes_from_the_toml(tmp_path: Path) -> None:
    write(tmp_path / ".unskein.toml", "[findings]\npackage_depth = 2\n")
    toml = load_toml_config(tmp_path, user_config=tmp_path / "nope.toml")

    assert resolve_findings_config(toml, None).package_depth == 2


@pytest.mark.parametrize("line", ["package_depth = 0", "package_depth = -1"])
def test_package_depth_must_be_positive(tmp_path: Path, line: str) -> None:
    write(tmp_path / ".unskein.toml", f"[findings]\n{line}\n")

    with pytest.raises(ConfigError) as raised:
        load_toml_config(tmp_path, user_config=tmp_path / "nope.toml")

    assert raised.value.key == ErrorKey.INVALID_VALUE
