from collections.abc import Callable
from pathlib import Path

import pathspec
import pytest

from unskein.parsers.models import ParseResult
from unskein.parsers.python_parser import PythonAdapter

IMPORT_LINE = "from pkg import dep"

NESTED_CONTEXTS = {
    "if_type_checking": f"if TYPE_CHECKING:\n    {IMPORT_LINE}\n",
    "if_else_branch": f"if FLAG:\n    pass\nelse:\n    {IMPORT_LINE}\n",
    "function": f"def run():\n    {IMPORT_LINE}\n",
    "async_function": f"async def run():\n    {IMPORT_LINE}\n",
    "class_body": f"class Holder:\n    {IMPORT_LINE}\n",
    "try_body": f"try:\n    {IMPORT_LINE}\nexcept ImportError:\n    pass\n",
    "except_handler": f"try:\n    pass\nexcept ImportError:\n    {IMPORT_LINE}\n",
    "try_else": f"try:\n    pass\nexcept ImportError:\n    pass\nelse:\n    {IMPORT_LINE}\n",
    "try_finally": f"try:\n    pass\nfinally:\n    {IMPORT_LINE}\n",
    "except_star": f"try:\n    pass\nexcept* ImportError:\n    {IMPORT_LINE}\n",
    "with_body": f"with ctx():\n    {IMPORT_LINE}\n",
    "async_with_body": f"async def run():\n    async with ctx():\n        {IMPORT_LINE}\n",
    "for_body": f"for item in items:\n    {IMPORT_LINE}\n",
    "for_else": f"for item in items:\n    pass\nelse:\n    {IMPORT_LINE}\n",
    "while_else": f"while FLAG:\n    pass\nelse:\n    {IMPORT_LINE}\n",
    "match_case": f"match value:\n    case 1:\n        {IMPORT_LINE}\n",
    "nested_function_in_class": f"class Holder:\n    def run(self):\n        {IMPORT_LINE}\n",
}


def parse_project(root: Path) -> ParseResult:
    """Discover and parse every Python file under root."""
    adapter = PythonAdapter()
    return adapter.parse(sorted(adapter.discover_files(root, pathspec.PathSpec([]))), root)


@pytest.mark.parametrize("source", NESTED_CONTEXTS.values(), ids=NESTED_CONTEXTS.keys())
def test_import_is_detected_in_every_nested_context(
    make_project: Callable[[dict[str, str]], Path], source: str
) -> None:
    root = make_project({"pkg/__init__.py": "", "pkg/dep.py": "", "pkg/mod.py": source})
    module = next(m for m in parse_project(root).modules if m.name == "pkg.mod")
    assert [(edge.target, edge.is_external) for edge in module.imports] == [("pkg.dep", False)]


def test_duplicate_reexport_resolves_to_first_in_code_not_shallowest(
    make_project: Callable[[dict[str, str]], Path],
) -> None:
    root = make_project(
        {
            "app/__init__.py": (
                "if True:\n    if True:\n        from ._deep import Engine\n"
                "from ._top import Engine\n"
            ),
            "app/_deep.py": "",
            "app/_top.py": "",
        }
    )
    reexports = [r for r in parse_project(root).re_exports if r.symbol_name == "Engine"]
    assert [r.original_module for r in reexports] == ["app._deep", "app._top"]


def test_wildcards_of_a_file_follow_the_order_of_the_code(
    make_project: Callable[[dict[str, str]], Path],
) -> None:
    source = "if True:\n    from pkg.a import *\nfrom pkg.b import *\n"
    root = make_project(
        {"pkg/__init__.py": "", "pkg/a.py": "", "pkg/b.py": "", "pkg/mod.py": source}
    )
    (module,) = [m for m in parse_project(root).modules if m.name == "pkg.mod"]
    assert [line for line, _ in module.stars.statements] == [2, 3]


def test_wildcards_follow_the_order_of_every_block_of_a_try(
    make_project: Callable[[dict[str, str]], Path],
) -> None:
    source = (
        "try:\n    from pkg.a import *\n"
        "except ImportError:\n    from pkg.b import *\n"
        "else:\n    from pkg.c import *\n"
        "finally:\n    from pkg.d import *\n"
    )
    files = {"pkg/__init__.py": "", "pkg/mod.py": source}
    files |= {f"pkg/{name}.py": "" for name in "abcd"}
    root = make_project(files)
    (module,) = [m for m in parse_project(root).modules if m.name == "pkg.mod"]
    assert [line for line, _ in module.stars.statements] == [2, 4, 6, 8]
