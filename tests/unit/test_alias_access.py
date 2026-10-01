from collections.abc import Callable
from pathlib import Path

import pathspec
import pytest

from unskein.graph.builder import build_graph
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import ImportKind, ParseResult
from unskein.parsers.python_parser import PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]

PACKAGE = {
    "pkg/__init__.py": ("from pkg.core.engine import Engine, Other\nVERSION = '1'\n"),
    "pkg/core/__init__.py": "",
    "pkg/core/engine.py": "class Engine: ...\nclass Other: ...\n",
    "pkg/util.py": "def helper(): ...\n",
    "pkg/sub/__init__.py": "from pkg.sub.impl import Thing\n",
    "pkg/sub/impl.py": "class Thing: ...\n",
}


def resolve(root: Path) -> ParseResult:
    """Parse and resolve every Python file under root.

    Args:
        root: Project directory.

    Returns:
        The parse result after indirection resolution.
    """
    adapter = PythonAdapter()
    files = sorted(adapter.discover_files(root, pathspec.PathSpec([])))
    return resolve_indirection(adapter.parse(files, root))


def edges_of(result: ParseResult, module: str) -> set[tuple[str, str | None]]:
    """Return the internal ``(target, symbol)`` pairs imported by one module.

    Args:
        result: Resolved parse result.
        module: Dotted module name.

    Returns:
        The pairs, without duplicates.
    """
    found = next(m for m in result.modules if m.name == module)
    return {(e.target, e.symbol_name) for e in found.imports if not e.is_external}


def consumer(source: str) -> dict[str, str]:
    """Add a consumer module to the shared package.

    Args:
        source: Source of ``pkg/use.py``.

    Returns:
        The project files.
    """
    return PACKAGE | {"pkg/use.py": source}


def test_alias_accesses_resolve_to_the_modules_that_define_the_names(
    make_project: MakeProject,
) -> None:
    root = make_project(consumer("import pkg as p\nx = p.Engine\ny = p.util.helper\n"))
    assert edges_of(resolve(root), "pkg.use") == {
        ("pkg.core.engine", "Engine"),
        ("pkg.util", "helper"),
    }


def test_plain_import_of_a_package_resolves_too(make_project: MakeProject) -> None:
    root = make_project(consumer("import pkg\nx = pkg.Engine\n"))
    assert edges_of(resolve(root), "pkg.use") == {("pkg.core.engine", "Engine")}


def test_submodule_package_reached_with_from_import_resolves(make_project: MakeProject) -> None:
    root = make_project(consumer("from pkg import sub\nx = sub.Thing\n"))
    assert edges_of(resolve(root), "pkg.use") == {("pkg.sub.impl", "Thing")}


@pytest.mark.parametrize(
    "source",
    [
        "import pkg as p\nregister(p)\nx = p.Engine\n",
        "import pkg as p\np = None\nx = p.Engine\n",
        "import pkg as p\np.Engine = 1\n",
        "import pkg as p\n",
        "import pkg as p\nx = 'p.Engine'\n",
        "import pkg as p\nimport pkg.util as p\nx = p.Engine\n",
    ],
    ids=["escapes", "rebound", "attribute_write", "unused", "only_in_a_string", "bound_twice"],
)
def test_unresolvable_uses_keep_the_edge_to_the_facade(
    make_project: MakeProject, source: str
) -> None:
    root = make_project(consumer(source))
    assert ("pkg", None) in edges_of(resolve(root), "pkg.use")


def test_attribute_defined_in_the_facade_itself_depends_on_the_facade(
    make_project: MakeProject,
) -> None:
    root = make_project(consumer("import pkg as p\nx = p.VERSION\n"))
    assert edges_of(resolve(root), "pkg.use") == {("pkg", "VERSION")}


def test_chain_that_resolves_to_the_importing_module_adds_no_self_edge(
    make_project: MakeProject,
) -> None:
    files = PACKAGE | {
        "pkg/core/engine.py": "import pkg as p\nclass Engine: ...\nx = p.Engine\n",
    }
    result = resolve(make_project(files))
    assert edges_of(result, "pkg.core.engine") == set()


def test_expanded_edges_inherit_the_kind_of_the_statement(make_project: MakeProject) -> None:
    root = make_project(consumer("def run():\n    import pkg as p\n    return p.Engine\n"))
    module = next(m for m in resolve(root).modules if m.name == "pkg.use")
    [edge] = [e for e in module.imports if not e.is_external]
    assert (edge.target, edge.kind) == ("pkg.core.engine", ImportKind.LAZY)


def test_several_chains_into_one_module_make_one_edge_of_weight_one(
    make_project: MakeProject,
) -> None:
    root = make_project(consumer("import pkg as p\nx = (p.Engine, p.Other)\n"))
    result = resolve(root)
    assert edges_of(result, "pkg.use") == {("pkg.core.engine", None)}
    assert build_graph(result).edges["pkg.use", "pkg.core.engine"]["weight"] == 1


def test_expanded_edges_come_out_in_module_order(make_project: MakeProject) -> None:
    root = make_project(consumer("import pkg as p\nx = (p.util.helper, p.Engine, p.sub.Thing)\n"))
    module = next(m for m in resolve(root).modules if m.name == "pkg.use")
    targets = [e.target for e in module.imports if not e.is_external]
    assert targets == ["pkg.core.engine", "pkg.sub.impl", "pkg.util"]


def test_resolve_indirection_does_not_mutate_its_input(make_project: MakeProject) -> None:
    root = make_project(consumer("import pkg as p\nx = p.Engine\n"))
    adapter = PythonAdapter()
    parsed = adapter.parse(sorted(adapter.discover_files(root, pathspec.PathSpec([]))), root)
    before = [(m.name, [(e.target, e.accessed) for e in m.imports]) for m in parsed.modules]
    resolve_indirection(parsed)
    assert before == [(m.name, [(e.target, e.accessed) for e in m.imports]) for m in parsed.modules]
