from pathlib import Path

import networkx as nx

from unskein.parsers.discovery import load_exclude_spec
from unskein.parsers.python_parser import PythonAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]


def unskein_internal_edges() -> set[tuple[str, str]]:
    adapter = PythonAdapter()
    src = REPO_ROOT / "src"
    files = sorted(adapter.discover_files(src, load_exclude_spec(src, [])))
    result = adapter.parse(files, src)
    return {(e.source, e.target) for m in result.modules for e in m.imports if not e.is_external}


def test_parsers_base_and_indirection_do_not_import_each_other() -> None:
    edges = unskein_internal_edges()
    base, indirection = "unskein.parsers.base", "unskein.parsers.indirection"
    assert not ((base, indirection) in edges and (indirection, base) in edges)


def test_unskein_source_has_no_import_tangles() -> None:
    graph = nx.DiGraph(sorted(unskein_internal_edges()))

    tangles = [sorted(group) for group in nx.strongly_connected_components(graph) if len(group) > 1]

    assert tangles == []
