from pathlib import Path

import pathspec

from unskein.config import AnalysisConfig, OptionalRules
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import ImportEdge, ParseResult
from unskein.parsers.python_parser import PythonAdapter

PROJECT = {
    "lib/__init__.py": "from lib.m import X\n",
    "lib/m.py": "X = 1\n",
    "app/__init__.py": "",
    "app/a.py": "from lib import X\nfrom lib.m import X as Y\n",
    "app/b.py": "import lib\nprint(lib.X)\n",
}


def _parsed(root: Path, *, api_leaks: bool) -> ParseResult:
    adapter = PythonAdapter(AnalysisConfig(optional_rules=OptionalRules(api_leaks=api_leaks)))
    files = sorted(adapter.discover_files(root, pathspec.PathSpec([])))
    return adapter.parse(files, root)


def _edges(result: ParseResult, module: str = "app.a") -> list[ImportEdge]:
    return next(m for m in result.modules if m.name == module).imports


def test_the_alias_is_recorded_only_when_it_differs(make_project) -> None:
    edges = _edges(_parsed(make_project(PROJECT), api_leaks=False))
    assert [(e.symbol_name, e.alias) for e in edges if e.symbol_name] == [("X", None), ("X", "Y")]


def test_resolution_records_the_module_the_statement_wrote(make_project) -> None:
    resolved = resolve_indirection(_parsed(make_project(PROJECT), api_leaks=True))
    edges = [e for e in _edges(resolved) if not e.is_external]
    assert [(e.target, e.written) for e in edges if e.symbol_name] == [
        ("lib.m", "lib"),
        ("lib.m", None),
    ]


def test_an_attribute_access_through_a_package_also_records_it(make_project) -> None:
    resolved = resolve_indirection(_parsed(make_project(PROJECT), api_leaks=True))
    edges = [e for e in _edges(resolved, "app.b") if not e.is_external]
    assert [(e.target, e.written) for e in edges] == [("lib.m", "lib")]


def test_nothing_is_recorded_with_the_option_off(make_project) -> None:
    resolved = resolve_indirection(_parsed(make_project(PROJECT), api_leaks=False))
    assert all(e.written is None for name in ("app.a", "app.b") for e in _edges(resolved, name))
