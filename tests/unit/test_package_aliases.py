from collections.abc import Callable
from pathlib import Path

import pathspec
import pytest

from unskein.config import AnalysisConfig, TomlAnalysis
from unskein.parsers.aliases import resolve_alias
from unskein.parsers.python_parser import PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]
EMPTY_SPEC = pathspec.PathSpec([])
ALIASED_PROJECT = {
    "src/verwaltung/__init__.py": "",
    "src/verwaltung/admin_web/__init__.py": "",
    "src/verwaltung/admin_web/api.py": "",
    "src/app/__init__.py": "",
    "src/app/main.py": "from admin_web.api import router\nimport admin_web\n",
}


def internal_edges(root: Path, config: AnalysisConfig | None = None) -> set[tuple[str, str]]:
    """Parse a project the way a scan does and return its internal (source, target) edges."""
    adapter = PythonAdapter(config)
    files = list(adapter.discover_files(root, EMPTY_SPEC, adapter.config.follow_symlinks))
    plan = adapter.plan_parse(files, root)
    edges = set()
    for task in plan.tasks:
        module = adapter.parse_task(task, plan.shared).module
        assert module is not None
        edges |= {(e.source, e.target) for e in module.imports if not e.is_external}
    return edges


def symlink_or_skip(link: Path, target: Path) -> None:
    """Create a directory symlink, or skip the test where the OS does not allow it."""
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("creating symlinks is not allowed here")


def test_resolve_alias_replaces_the_longest_aliased_prefix() -> None:
    aliases = {"web": "pkg.web", "web.api": "pkg.api"}

    assert resolve_alias("web.api.routes", aliases) == "pkg.api.routes"
    assert resolve_alias("web.views", aliases) == "pkg.web.views"
    assert resolve_alias("webby", aliases) == "webby"


def test_git_symlink_stub_makes_imports_through_the_alias_internal(
    make_project: MakeProject,
) -> None:
    root = make_project({**ALIASED_PROJECT, "src/admin_web": "verwaltung/admin_web"})

    edges = internal_edges(root)

    assert ("app.main", "verwaltung.admin_web.api") in edges
    assert ("app.main", "verwaltung.admin_web") in edges


def test_symlinked_package_makes_imports_through_the_alias_internal(
    make_project: MakeProject,
) -> None:
    root = make_project(ALIASED_PROJECT)
    symlink_or_skip(root / "src" / "admin_web", root / "src" / "verwaltung" / "admin_web")

    assert ("app.main", "verwaltung.admin_web.api") in internal_edges(root)


def test_followed_symlink_names_files_by_their_real_package(make_project: MakeProject) -> None:
    root = make_project(ALIASED_PROJECT)
    symlink_or_skip(root / "src" / "admin_web", root / "src" / "verwaltung" / "admin_web")
    adapter = PythonAdapter(AnalysisConfig(follow_symlinks=True))
    files = list(adapter.discover_files(root, EMPTY_SPEC, follow_symlinks=True))

    plan = adapter.plan_parse(files, root)

    assert "verwaltung.admin_web.api" in plan.shared.modules
    assert not any(name.startswith("admin_web") for name in plan.shared.modules)


def test_stub_pointing_outside_the_project_is_not_an_alias(make_project: MakeProject) -> None:
    root = make_project({**ALIASED_PROJECT, "src/admin_web": "../../elsewhere"})
    (root.parent / "elsewhere").mkdir(exist_ok=True)

    assert not any(target.startswith("verwaltung") for _, target in internal_edges(root))


def test_plain_text_file_without_suffix_is_not_an_alias(make_project: MakeProject) -> None:
    root = make_project({**ALIASED_PROJECT, "src/admin_web": "not a path\nat all\n"})

    assert not any(target.startswith("verwaltung") for _, target in internal_edges(root))


def test_configured_module_aliases_resolve_imports(make_project: MakeProject) -> None:
    root = make_project(ALIASED_PROJECT)
    config = AnalysisConfig(module_aliases={"admin_web": "verwaltung.admin_web"})

    assert ("app.main", "verwaltung.admin_web.api") in internal_edges(root, config)


def test_module_aliases_must_be_dotted_module_names() -> None:
    with pytest.raises(ValueError, match="dotted module names"):
        TomlAnalysis(module_aliases={"admin-web": "verwaltung.admin_web"})
