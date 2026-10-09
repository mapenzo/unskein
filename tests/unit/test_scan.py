import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from unskein import pipeline
from unskein.ai.models import AIFailure, AIReport, Problem
from unskein.errors import ConfigError, ErrorKey, UnskeinError
from unskein.i18n import Lang
from unskein.report.markdown import AIStatus
from unskein.scan import ScanOptions, execute_scan, parse_project, prepare_scan

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


def test_no_ai_flag_drops_the_ai_config(make_project: MakeProject) -> None:
    root = make_project({"a.py": ""})
    model_env = {"UNSKEIN_AI_MODEL": "ollama/x"}
    context = prepare(ScanOptions(path=root, no_ai=True), model_env)
    assert context.ai_disabled is True
    assert context.ai_config is None
    configured = prepare(ScanOptions(path=root), model_env)
    assert configured.ai_config is not None
    assert configured.ai_config.model == "ollama/x"
    assert prepare(ScanOptions(path=root)).ai_config is None


def test_status_is_disabled_with_no_ai(circular_imports: Path, tmp_path: Path) -> None:
    options = ScanOptions(path=circular_imports, no_ai=True)
    assert execute_scan(prepare(options, tmp=tmp_path)).ai_status is AIStatus.DISABLED


def test_status_is_not_configured_without_a_model(circular_imports: Path, tmp_path: Path) -> None:
    outcome = execute_scan(prepare(ScanOptions(path=circular_imports), tmp=tmp_path))
    assert outcome.ai_status is AIStatus.NOT_CONFIGURED
    assert outcome.ai_report is None


def test_status_is_present_with_a_valid_answer(
    circular_imports: Path, tmp_path: Path, fake_llm: Any
) -> None:
    fake_llm.content = AIReport(
        summary="s", architecture_health="fair", problems=[]
    ).model_dump_json()
    options = ScanOptions(path=circular_imports)
    context = prepare(options, {"UNSKEIN_AI_MODEL": "ollama/x"}, tmp=tmp_path)
    outcome = execute_scan(context)
    assert outcome.ai_status is AIStatus.PRESENT
    assert outcome.ai_report is not None
    assert len(fake_llm.calls) == 1


def test_status_is_failed_with_an_unusable_answer(
    circular_imports: Path, tmp_path: Path, fake_llm: Any
) -> None:
    fake_llm.content = "garbage"
    context = prepare(
        ScanOptions(path=circular_imports), {"UNSKEIN_AI_MODEL": "ollama/x"}, tmp=tmp_path
    )
    outcome = execute_scan(context)
    assert outcome.ai_status is AIStatus.FAILED
    assert outcome.ai_outcome is not None
    assert outcome.ai_outcome.failure is AIFailure.INVALID_RESPONSE


def test_the_client_is_not_built_when_ai_is_disabled(
    circular_imports: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(config: object) -> None:
        raise AssertionError("AIClient built with --no-ai")

    monkeypatch.setattr("unskein.scan.AIClient", refuse)
    options = ScanOptions(path=circular_imports, no_ai=True)
    execute_scan(prepare(options, {"UNSKEIN_AI_MODEL": "ollama/x"}, tmp=tmp_path))


def test_hallucinated_modules_are_dropped_from_the_report(
    circular_imports: Path, tmp_path: Path, fake_llm: Any
) -> None:
    problems = [
        Problem(
            severity="high",
            title="ghost",
            description="d",
            affected_modules=["ghost.mod"],
            recommendation="r",
        ),
        Problem(
            severity="high",
            title="real",
            description="d",
            affected_modules=["app.a", "ghost.mod"],
            recommendation="r",
        ),
    ]
    report = AIReport(summary="s", architecture_health="concerning", problems=problems)
    fake_llm.content = report.model_dump_json()
    context = prepare(
        ScanOptions(path=circular_imports), {"UNSKEIN_AI_MODEL": "ollama/x"}, tmp=tmp_path
    )
    grounded = execute_scan(context).ai_report
    assert grounded is not None
    assert [(p.title, p.affected_modules) for p in grounded.problems] == [("real", ["app.a"])]


def test_dropped_problems_are_counted_and_logged(
    circular_imports: Path,
    tmp_path: Path,
    fake_llm: Any,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(logging.getLogger("unskein"), "propagate", True)
    caplog.set_level(logging.WARNING, logger="unskein")
    ghost = Problem(
        severity="high",
        title="secret title",
        description="d",
        affected_modules=["ghost.mod"],
        recommendation="r",
    )
    report = AIReport(summary="s", architecture_health="concerning", problems=[ghost])
    fake_llm.content = report.model_dump_json()
    context = prepare(
        ScanOptions(path=circular_imports), {"UNSKEIN_AI_MODEL": "ollama/x"}, tmp=tmp_path
    )
    outcome = execute_scan(context)
    assert outcome.ai_outcome is not None
    assert outcome.ai_outcome.dropped_problems == 1
    messages = [record.getMessage() for record in caplog.records]
    assert "Discarded 1 AI problem(s) that named no module of the project" in messages
    assert "secret title" not in caplog.text


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


def test_project_with_only_stubs_is_a_usage_error(make_project: MakeProject) -> None:
    root = make_project({"app/core.pyi": "X: int\n"})
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


def test_parallel_threshold_from_toml_routes_parsing_through_the_pool(
    make_project: MakeProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_project(
        {
            "pkg/__init__.py": "",
            "pkg/a.py": "import pkg\n",
            "pkg/b.py": "from pkg import a\n",
            ".unskein.toml": "[analysis]\nparallel_threshold = 2\nmax_workers = 2\n",
        }
    )
    pools: list[dict[str, Any]] = []
    real_pool = pipeline.ProcessPoolExecutor

    def recording_pool(**kwargs: Any) -> Any:
        pools.append(kwargs)
        return real_pool(**kwargs)

    monkeypatch.setattr(pipeline, "ProcessPoolExecutor", recording_pool)

    outcome = execute_scan(prepare(ScanOptions(path=root, no_ai=True), tmp=root))

    assert len(pools) == 1
    assert pools[0]["max_workers"] == 2
    assert outcome.result.graph.number_of_edges() == 2


def test_findings_flag_beats_the_toml(make_project: MakeProject) -> None:
    root = make_project({"a.py": "", ".unskein.toml": "[findings]\nenabled = true\n"})

    context = prepare(ScanOptions(path=root, findings=False))

    assert context.findings.enabled is False


def test_pyproject_scripts_are_entry_points_of_the_parse(make_project: MakeProject) -> None:
    root = make_project(
        {"tool.py": "", "pyproject.toml": '[project.scripts]\ntool = "tool:main"\n'}
    )

    parsed = parse_project(prepare(ScanOptions(path=root)))

    assert parsed.entry_points == ("tool",)


def test_scan_reports_orphans_except_entry_points(make_project: MakeProject) -> None:
    root = make_project(
        {
            "tool.py": "",
            "stray.py": "",
            "pyproject.toml": '[project.scripts]\ntool = "tool:main"\n',
        }
    )

    outcome = execute_scan(prepare(ScanOptions(path=root, no_ai=True)))

    assert [f.modules for f in outcome.result.findings] == [("stray",)]


def test_scan_warns_about_a_declared_layer_that_matches_no_module(
    make_project: MakeProject, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_project({"web.py": "", ".unskein.toml": '[layers]\norder = ["web", "cor"]\n'})
    # The CLI tests turn propagation off on this logger; caplog needs it on.
    logger = logging.getLogger("unskein")
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "propagate", True)

    with caplog.at_level(logging.WARNING, logger="unskein"):
        execute_scan(prepare(ScanOptions(path=root, no_ai=True)))

    assert [record.getMessage() for record in caplog.records] == [
        "Layer cor in [layers] matches no module of the project"
    ]


def test_scan_does_not_warn_about_a_declared_layer_that_only_scripts_match(
    make_project: MakeProject, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "lib"\n[tool.setuptools]\npackages = ["lib"]\n',
            "lib/__init__.py": "",
            "lib/api.py": "",
            "cookbook/demo.py": "from lib import api\n",
            ".unskein.toml": '[layers]\norder = ["cookbook", "lib"]\n',
        }
    )
    logger = logging.getLogger("unskein")
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "propagate", True)

    with caplog.at_level(logging.WARNING, logger="unskein"):
        execute_scan(prepare(ScanOptions(path=root, no_ai=True)))

    assert caplog.records == []
