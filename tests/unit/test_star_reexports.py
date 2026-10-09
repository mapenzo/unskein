from collections.abc import Callable
from pathlib import Path

import pathspec

from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import STAR_EXPORT, ParseResult, ReExport, WarningCode
from unskein.parsers.python_parser import PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]

NETWORK_LIKE = {
    "pkg/__init__.py": "from pkg.exception import *\nfrom pkg.classes import *\n",
    "pkg/exception.py": "class PkgError(Exception): ...\n_internal = 1\n",
    "pkg/classes/__init__.py": (
        "from pkg.classes.graph import Graph\nfrom pkg.classes.multi import *\n"
    ),
    "pkg/classes/graph.py": "class Graph: ...\n",
    "pkg/classes/multi.py": "__all__ = ['MultiGraph']\nclass MultiGraph: ...\nclass Hidden: ...\n",
}


def parse(root: Path) -> ParseResult:
    """Discover and parse every Python file under root.

    Args:
        root: Project directory.

    Returns:
        The parse result, before indirection resolution.
    """
    adapter = PythonAdapter()
    return adapter.parse(sorted(adapter.discover_files(root, pathspec.PathSpec([]))), root)


def targets_of(result: ParseResult, module: str) -> set[tuple[str, str | None]]:
    """Return the internal ``(target, symbol)`` pairs of one module.

    Args:
        result: Parse result.
        module: Dotted module name.

    Returns:
        The pairs, without duplicates.
    """
    found = next(m for m in result.modules if m.name == module)
    return {(e.target, e.symbol_name) for e in found.imports if not e.is_external}


def test_star_in_a_facade_is_a_reexport_without_warning(make_project: MakeProject) -> None:
    result = parse(make_project(NETWORK_LIKE))
    assert ReExport("pkg", "pkg.classes", STAR_EXPORT) in result.re_exports
    assert ReExport("pkg.classes", "pkg.classes.multi", STAR_EXPORT) in result.re_exports
    assert WarningCode.STAR_IMPORT not in [w.code for w in result.warnings]


def test_star_outside_a_facade_is_recorded_without_warning(make_project: MakeProject) -> None:
    files = {"app/__init__.py": "", "app/a.py": "from app.b import *\n", "app/b.py": "X = 1\n"}
    result = parse(make_project(files))
    assert result.warnings == []
    assert [m.stars.statements for m in result.modules if m.name == "app.a"] == [((1, "app.b"),)]
    assert result.re_exports == []


def test_star_of_an_external_module_is_ignored(make_project: MakeProject) -> None:
    result = parse(make_project({"app/__init__.py": "from os.path import *\n", "app/a.py": ""}))
    assert result.warnings == []


def test_alias_access_follows_star_reexports_to_the_defining_module(
    make_project: MakeProject,
) -> None:
    files = NETWORK_LIKE | {
        "use.py": "import pkg as nx\nx = (nx.Graph, nx.MultiGraph, nx.PkgError)\n"
    }
    assert targets_of(resolve_indirection(parse(make_project(files))), "use") == {
        ("pkg.classes.graph", "Graph"),
        ("pkg.classes.multi", "MultiGraph"),
        ("pkg.exception", "PkgError"),
    }


def test_symbol_import_follows_star_reexports(make_project: MakeProject) -> None:
    files = NETWORK_LIKE | {"use.py": "from pkg import Graph, PkgError\n"}
    assert targets_of(resolve_indirection(parse(make_project(files))), "use") == {
        ("pkg.classes.graph", "Graph"),
        ("pkg.exception", "PkgError"),
    }


def test_names_left_out_by_all_or_private_stay_on_the_facade(make_project: MakeProject) -> None:
    files = NETWORK_LIKE | {"use.py": "from pkg import Hidden, _internal\n"}
    assert targets_of(resolve_indirection(parse(make_project(files))), "use") == {
        ("pkg", "Hidden"),
        ("pkg", "_internal"),
    }


def test_explicit_reexport_before_a_star_wins(make_project: MakeProject) -> None:
    files = {
        "pkg/__init__.py": "from pkg.a import Thing\nfrom pkg.b import *\n",
        "pkg/a.py": "class Thing: ...\n",
        "pkg/b.py": "class Thing: ...\n",
        "use.py": "from pkg import Thing\n",
    }
    assert targets_of(resolve_indirection(parse(make_project(files))), "use") == {
        ("pkg.a", "Thing")
    }


def test_star_reexport_cycle_terminates(make_project: MakeProject) -> None:
    files = {
        "a/__init__.py": "from a.b import *\n",
        "a/b/__init__.py": "from a import *\nX = 1\n",
        "use.py": "from a import X\n",
    }
    assert targets_of(resolve_indirection(parse(make_project(files))), "use") == {("a.b", "X")}


def test_facade_all_does_not_hide_star_reexports(make_project: MakeProject) -> None:
    files = {
        "pkg/__init__.py": "from pkg.a import *\n__all__ = ['Thing']\n",
        "pkg/a.py": "class Thing: ...\n",
        "use.py": "from pkg import Thing\n",
    }
    assert targets_of(resolve_indirection(parse(make_project(files))), "use") == {
        ("pkg.a", "Thing")
    }


def test_explicit_import_after_a_star_wins(make_project: MakeProject) -> None:
    files = {
        "pkg/__init__.py": "from pkg.b import *\nfrom pkg.a import Thing\n",
        "pkg/a.py": "class Thing: ...\n",
        "pkg/b.py": "class Thing: ...\n",
        "use.py": "from pkg import Thing\n",
    }
    assert targets_of(resolve_indirection(parse(make_project(files))), "use") == {
        ("pkg.a", "Thing")
    }


def test_facade_own_definition_before_a_star_wins(make_project: MakeProject) -> None:
    files = {
        "pkg/__init__.py": "class Thing: ...\nfrom pkg.b import *\n",
        "pkg/b.py": "class Thing: ...\n",
        "use.py": "from pkg import Thing\n",
    }
    assert targets_of(resolve_indirection(parse(make_project(files))), "use") == {("pkg", "Thing")}
