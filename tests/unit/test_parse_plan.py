from collections.abc import Callable
from pathlib import Path

from unskein.config import AnalysisConfig
from unskein.parsers.models import FileParseResult, ParseResult, ParseWarning, WarningCode
from unskein.parsers.python_parser import ProjectIndex, PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]


def test_plan_parse_names_every_file_in_the_given_order(make_project: MakeProject) -> None:
    root = make_project({"pkg/__init__.py": "", "pkg/a.py": "", "pkg/b.py": ""})
    files = [root / "pkg" / "b.py", root / "pkg" / "a.py", root / "pkg" / "__init__.py"]

    plan = PythonAdapter().plan_parse(files, root)

    assert plan.tasks == [(files[0], "pkg.b"), (files[1], "pkg.a"), (files[2], "pkg")]


def test_plan_parse_shares_one_index_of_all_project_modules(make_project: MakeProject) -> None:
    root = make_project({"pkg/__init__.py": "", "pkg/a.py": ""})

    plan = PythonAdapter().plan_parse([root / "pkg" / "a.py", root / "pkg" / "__init__.py"], root)

    assert isinstance(plan.shared, ProjectIndex)
    assert plan.shared.modules == {"pkg", "pkg.a"}


def test_parse_task_parses_one_file_with_the_shared_index(make_project: MakeProject) -> None:
    root = make_project({"pkg/__init__.py": "", "pkg/a.py": "import pkg\n"})
    adapter = PythonAdapter()
    plan = adapter.plan_parse([root / "pkg" / "a.py", root / "pkg" / "__init__.py"], root)

    result = adapter.parse_task(plan.tasks[0], plan.shared)

    assert isinstance(result, FileParseResult)
    assert result.module is not None
    assert [(e.source, e.target) for e in result.module.imports] == [("pkg.a", "pkg")]


def test_from_file_results_keeps_task_order_and_skips_failed_files(tmp_path: Path) -> None:
    warning = ParseWarning(WarningCode.PARSE_ERROR, tmp_path / "x.py", None, "boom")
    results = [FileParseResult(None, warnings=[warning])]

    combined = ParseResult.from_file_results("python", results)

    assert combined.modules == []
    assert combined.warnings == [warning]
    assert combined.language == "python"


FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_plan_names_workspace_members_by_import_name() -> None:
    root = FIXTURES / "workspace_monorepo"
    files = sorted(root.rglob("*.py"))
    plan = PythonAdapter(AnalysisConfig()).plan_parse(files, root)
    names = {path.relative_to(root).as_posix(): name for path, name in plan.tasks}
    assert names["enterprise/core_enterprise/hooks.py"] == "core_enterprise.hooks"
    assert names["enterprise/legacy/banned.py"] == "enterprise.legacy.banned"
    assert names[".circleci/scripts/run.py"] == ".circleci/scripts/run.py"
    assert plan.shared.top_level == frozenset({"core", "core_enterprise", "enterprise", "cookbook"})
    assert "cookbook.demo" in plan.shared.unpackaged
    assert "core.engine" not in plan.shared.unpackaged
    assert plan.entry_points == ("core.cli",)
