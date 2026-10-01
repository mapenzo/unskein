from collections.abc import Callable
from pathlib import Path

import pathspec
import pytest

from unskein.parsers import python_parser
from unskein.parsers.models import ImportEdge, ParseResult
from unskein.parsers.python_parser import ProjectIndex, PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]

PACKAGE = {
    "pkg/__init__.py": "from pkg.core.engine import Engine\n",
    "pkg/core/__init__.py": "",
    "pkg/core/engine.py": "class Engine: ...\n",
    "pkg/util.py": "def helper(): ...\n",
}


def parse(root: Path) -> ParseResult:
    """Discover and parse every Python file under root.

    Args:
        root: Project directory.

    Returns:
        The parse result, with imports not yet resolved.
    """
    adapter = PythonAdapter()
    return adapter.parse(sorted(adapter.discover_files(root, pathspec.PathSpec([]))), root)


def edges_of(result: ParseResult, module: str) -> list[ImportEdge]:
    """Return the internal import edges of one module.

    Args:
        result: Parse result.
        module: Dotted module name.

    Returns:
        Its edges whose target lies inside the project.
    """
    found = next(m for m in result.modules if m.name == module)
    return [edge for edge in found.imports if not edge.is_external]


def test_project_index_knows_which_modules_are_packages() -> None:
    index = ProjectIndex.from_names({"a", "a.b", "a.b.c", "a.d", "e"})
    assert index.packages == frozenset({"a", "a.b"})
    assert index.is_package("a.b") and not index.is_package("a.d") and not index.is_package("e")


def test_alias_of_a_package_records_its_attribute_chains(make_project: MakeProject) -> None:
    root = make_project(
        PACKAGE
        | {"pkg/use.py": "import pkg as p\n\ndef run():\n    return p.Engine, p.util.helper\n"}
    )
    [edge] = edges_of(parse(root), "pkg.use")
    assert (edge.target, edge.accessed, edge.escapes) == ("pkg", ("Engine", "util.helper"), False)


def test_plain_import_of_a_package_is_tracked_under_its_own_name(make_project: MakeProject) -> None:
    root = make_project(PACKAGE | {"pkg/use.py": "import pkg\nx = pkg.Engine\n"})
    [edge] = edges_of(parse(root), "pkg.use")
    assert edge.accessed == ("Engine",)


def test_submodule_that_is_a_package_is_tracked_through_from_import(
    make_project: MakeProject,
) -> None:
    root = make_project(PACKAGE | {"pkg/use.py": "from pkg import core\nx = core.engine.Engine\n"})
    [edge] = edges_of(parse(root), "pkg.use")
    assert (edge.target, edge.accessed) == ("pkg.core", ("engine.Engine",))


def test_a_bare_use_marks_the_import_as_escaping(make_project: MakeProject) -> None:
    root = make_project(PACKAGE | {"pkg/use.py": "import pkg as p\nregister(p)\nx = p.Engine\n"})
    [edge] = edges_of(parse(root), "pkg.use")
    assert (edge.accessed, edge.escapes) == (("Engine",), True)


@pytest.mark.parametrize(
    "source",
    [
        "import pkg.util as p\nx = p.helper\n",
        "import pkg.core.engine as p\nx = p.Engine\n",
        "from pkg.util import helper\nx = helper\n",
        "import pkg.util\nx = pkg.util.helper\n",
    ],
    ids=["alias_of_a_module", "alias_of_a_leaf_module", "symbol_import", "dotted_without_alias"],
)
def test_imports_that_do_not_bind_a_package_are_not_analyzed(
    make_project: MakeProject, source: str
) -> None:
    root = make_project(PACKAGE | {"pkg/use.py": source})
    for edge in edges_of(parse(root), "pkg.use"):
        assert (edge.accessed, edge.escapes) == ((), False)


def test_a_name_bound_twice_is_not_analyzed(make_project: MakeProject) -> None:
    root = make_project(
        PACKAGE | {"pkg/use.py": "import pkg as p\nimport pkg.util as p\nx = p.Engine\n"}
    )
    for edge in edges_of(parse(root), "pkg.use"):
        assert (edge.accessed, edge.escapes) == ((), False)


def test_the_module_is_only_walked_when_it_imports_a_package(
    make_project: MakeProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("usage analysis must not run")

    monkeypatch.setattr(python_parser, "collect_name_usage", fail)
    root = make_project(
        {
            "app/__init__.py": "",
            "app/a.py": "import os\nfrom app.b import f\n",
            "app/b.py": "f = 1\n",
        }
    )
    assert edges_of(parse(root), "app.a")
