from collections.abc import Callable
from pathlib import Path

import pathspec
import pytest

from unskein.parsers.models import ImportEdge, ImportKind
from unskein.parsers.python_parser import PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]

KIND_CASES = {
    "top_level": ("from pkg import dep\n", ImportKind.MODULE),
    "plain_import": ("import pkg.dep\n", ImportKind.MODULE),
    "try_except": (
        "try:\n    from pkg import dep\nexcept ImportError:\n    pass\n",
        ImportKind.MODULE,
    ),
    "class_body": ("class Holder:\n    from pkg import dep\n", ImportKind.MODULE),
    "function": ("def run():\n    from pkg import dep\n", ImportKind.LAZY),
    "async_function": ("async def run():\n    from pkg import dep\n", ImportKind.LAZY),
    "method": ("class Holder:\n    def run(self):\n        from pkg import dep\n", ImportKind.LAZY),
    "plain_import_in_function": ("def run():\n    import pkg.dep\n", ImportKind.LAZY),
    "type_checking_name": (
        "if TYPE_CHECKING:\n    from pkg import dep\n",
        ImportKind.TYPE_CHECKING,
    ),
    "type_checking_attribute": (
        "import typing\nif typing.TYPE_CHECKING:\n    from pkg import dep\n",
        ImportKind.TYPE_CHECKING,
    ),
    "type_checking_star_import": (
        "if TYPE_CHECKING:\n    from pkg.dep import *\n",
        ImportKind.TYPE_CHECKING,
    ),
    "lazy_inside_type_checking": (
        "if TYPE_CHECKING:\n    def run():\n        from pkg import dep\n",
        ImportKind.TYPE_CHECKING,
    ),
    "type_checking_inside_function": (
        "def run():\n    if TYPE_CHECKING:\n        from pkg import dep\n",
        ImportKind.TYPE_CHECKING,
    ),
    "else_of_type_checking": (
        "if TYPE_CHECKING:\n    pass\nelse:\n    from pkg import dep\n",
        ImportKind.MODULE,
    ),
    "body_of_not_type_checking": (
        "if not TYPE_CHECKING:\n    from pkg import dep\n",
        ImportKind.MODULE,
    ),
}


def internal_kinds(root: Path) -> list[ImportKind]:
    """Return the kind of every internal import of ``pkg.mod``, in code order.

    Args:
        root: Project directory holding ``pkg/mod.py``.

    Returns:
        The kinds of the edges whose target lies inside the project.
    """
    adapter = PythonAdapter()
    files = sorted(adapter.discover_files(root, pathspec.PathSpec([])))
    module = next(m for m in adapter.parse(files, root).modules if m.name == "pkg.mod")
    return [edge.kind for edge in module.imports if not edge.is_external]


@pytest.mark.parametrize(("source", "expected"), KIND_CASES.values(), ids=KIND_CASES.keys())
def test_import_kind_follows_where_the_statement_sits(
    make_project: MakeProject, source: str, expected: ImportKind
) -> None:
    root = make_project({"pkg/__init__.py": "", "pkg/dep.py": "", "pkg/mod.py": source})
    assert internal_kinds(root) == [expected]


def test_edge_kind_defaults_to_module() -> None:
    assert ImportEdge("a", "b", False).kind is ImportKind.MODULE


def test_stronger_and_weaker_rank_by_how_much_the_import_runs() -> None:
    assert ImportKind.MODULE.stronger(ImportKind.LAZY) is ImportKind.MODULE
    assert ImportKind.LAZY.stronger(ImportKind.TYPE_CHECKING) is ImportKind.LAZY
    assert ImportKind.TYPE_CHECKING.stronger(ImportKind.TYPE_CHECKING) is ImportKind.TYPE_CHECKING
    assert ImportKind.MODULE.weaker(ImportKind.LAZY) is ImportKind.LAZY
    assert ImportKind.LAZY.weaker(ImportKind.TYPE_CHECKING) is ImportKind.TYPE_CHECKING
    assert ImportKind.LAZY.weaker(ImportKind.MODULE) is ImportKind.LAZY
