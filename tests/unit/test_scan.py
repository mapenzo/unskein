from collections.abc import Callable
from pathlib import Path

import pytest

from unskein.errors import ConfigError, ErrorKey, UnskeinError
from unskein.i18n import Lang
from unskein.report.markdown import AIStatus
from unskein.scan import ScanOptions, execute_scan, prepare_scan

MakeProject = Callable[[dict[str, str]], Path]


def prepare(options: ScanOptions, env: dict[str, str] | None = None, tmp: Path | None = None):
    """Prepare a scan isolated from the real environment and user config.

    Args:
        options: Scan options.
        env: Environment variables to use instead of ``os.environ``.
        tmp: Directory for a non-existent user config; defaults to the scan path.

    Returns:
        The prepared scan context.
    """
    user_config = (tmp or options.path) / "no-user-config.toml"
    return prepare_scan(options, env=env or {}, user_config=user_config)


def test_language_comes_from_project_toml_unless_flag_given(make_project: MakeProject) -> None:
    root = make_project({"a.py": "", ".unskein.toml": '[general]\nlang = "es"\n'})
    assert prepare(ScanOptions(path=root)).lang is Lang.ES
    assert prepare(ScanOptions(path=root, lang="en")).lang is Lang.EN


def test_invalid_toml_raises_config_error(make_project: MakeProject) -> None:
    root = make_project({"a.py": "", ".unskein.toml": "[analysis]\nbogus = 1\n"})
    with pytest.raises(ConfigError):
        prepare(ScanOptions(path=root))


def test_ai_status_reflects_flags_and_config(make_project: MakeProject) -> None:
    root = make_project({"a.py": ""})
    model_env = {"UNSKEIN_AI_MODEL": "ollama/x"}
    assert prepare(ScanOptions(path=root, no_ai=True), model_env).ai_status is AIStatus.DISABLED
    assert prepare(ScanOptions(path=root)).ai_status is AIStatus.NOT_CONFIGURED
    assert prepare(ScanOptions(path=root), model_env).ai_status is AIStatus.UNAVAILABLE


def test_execute_analyzes_the_project(circular_imports: Path, tmp_path: Path) -> None:
    outcome = execute_scan(prepare(ScanOptions(path=circular_imports, no_ai=True), tmp=tmp_path))
    assert outcome.result.cycles == [["app.a", "app.b"]]
    assert outcome.ai_report is None


def test_missing_path_is_a_usage_error(tmp_path: Path) -> None:
    context = prepare(ScanOptions(path=tmp_path / "nope"), tmp=tmp_path)
    with pytest.raises(UnskeinError) as exc:
        execute_scan(context)
    assert exc.value.key is ErrorKey.PATH_NOT_FOUND


def test_project_without_python_files_is_a_usage_error(make_project: MakeProject) -> None:
    root = make_project({"README.md": "hi"})
    with pytest.raises(UnskeinError) as exc:
        execute_scan(prepare(ScanOptions(path=root)))
    assert exc.value.key is ErrorKey.NO_FILES_FOUND


def test_tests_are_excluded_unless_requested(make_project: MakeProject) -> None:
    root = make_project({"app/__init__.py": "", "tests/test_app.py": "import app\n"})
    default = execute_scan(prepare(ScanOptions(path=root)))
    with_tests = execute_scan(prepare(ScanOptions(path=root, include_tests=True)))
    assert "tests.test_app" not in default.result.graph
    assert "tests.test_app" in with_tests.result.graph


def test_cli_excludes_and_toml_excludes_both_apply(make_project: MakeProject) -> None:
    root = make_project(
        {
            "keep.py": "",
            "gen/auto.py": "",
            "legacy/old.py": "",
            ".unskein.toml": '[analysis]\nexclude = ["gen/"]\n',
        }
    )
    outcome = execute_scan(prepare(ScanOptions(path=root, exclude=("legacy/",))))
    assert set(outcome.result.graph.nodes) == {"keep"}
