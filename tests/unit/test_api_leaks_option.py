import pathspec
import pytest

from unskein.config import (
    AnalysisConfig,
    AnalysisFlags,
    OptionalRules,
    TomlAnalysis,
    TomlConfig,
    resolve_analysis_config,
)
from unskein.parsers.python_parser import PythonAdapter


def _resolved(toml_value: bool | None, flag: bool | None) -> AnalysisConfig:
    toml = TomlConfig(analysis=TomlAnalysis(api_leaks=toml_value))
    return resolve_analysis_config(toml, AnalysisFlags(api_leaks=flag))


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
def test_api_leaks_is_off_by_default_and_the_flag_wins(
    toml_value: bool | None, flag: bool | None, expected: bool
) -> None:
    assert _resolved(toml_value, flag).optional_rules.api_leaks is expected


def test_star_fixes_and_api_leaks_resolve_independently() -> None:
    toml = TomlConfig(analysis=TomlAnalysis(star_fixes=True))
    config = resolve_analysis_config(toml, AnalysisFlags(api_leaks=True))
    assert config.optional_rules == OptionalRules(star_fixes=True, api_leaks=True)


def test_the_parse_plan_carries_the_option(make_project) -> None:
    root = make_project({"app/__init__.py": "", "app/a.py": "X = 1\n"})
    adapter = PythonAdapter(AnalysisConfig(optional_rules=OptionalRules(api_leaks=True)))
    files = sorted(adapter.discover_files(root, pathspec.PathSpec([])))
    assert adapter.parse(files, root).api_leaks is True
    default = PythonAdapter(AnalysisConfig())
    assert default.parse(files, root).api_leaks is False
