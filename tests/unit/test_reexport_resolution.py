import copy
from pathlib import Path

import pathspec

from unskein.parsers.indirection import (
    MAX_RESOLUTION_DEPTH,
    build_reexport_index,
    resolve_indirection,
    resolve_target,
)
from unskein.parsers.models import ImportEdge, ModuleInfo, ParseResult, ReExport, WarningCode
from unskein.parsers.python_parser import PythonAdapter

Edge = tuple[str, str, str | None]


def parse_fixture(root: Path) -> ParseResult:
    adapter = PythonAdapter()
    return adapter.parse(sorted(adapter.discover_files(root, pathspec.PathSpec([]))), root)


def internal_edges(result: ParseResult) -> set[Edge]:
    return {
        (e.source, e.target, e.symbol_name)
        for m in result.modules
        for e in m.imports
        if not e.is_external
    }


def single_module_result(edges: list[ImportEdge], re_exports: list[ReExport]) -> ParseResult:
    module = ModuleInfo("app.use", Path("app/use.py"), edges)
    return ParseResult(modules=[module], language="python", re_exports=re_exports)


def test_chain_rewrites_consumer_edge_to_defining_module(reexport_chain: Path) -> None:
    resolved = resolve_indirection(parse_fixture(reexport_chain))
    assert ("app.consumer", "app.core.impl.engine", "Engine") in internal_edges(resolved)
    assert ("app.consumer", "app", "Engine") not in internal_edges(resolved)
    assert resolved.warnings == []


def test_adapter_delegates_to_shared_resolution(reexport_chain: Path) -> None:
    result = parse_fixture(reexport_chain)
    assert PythonAdapter().resolve_indirection(result) == resolve_indirection(result)


def test_facade_edges_are_resolved_too(reexport_chain: Path) -> None:
    edges = internal_edges(resolve_indirection(parse_fixture(reexport_chain)))
    assert ("app", "app.core.impl.engine", "Engine") in edges


def test_reexport_cycle_yields_one_warning_per_cycle(reexport_cycle: Path) -> None:
    resolved = resolve_indirection(parse_fixture(reexport_cycle))
    assert ("app.user", "app.a", "Thing") in internal_edges(resolved)
    [warning] = resolved.warnings
    assert warning.code is WarningCode.REEXPORT_CYCLE
    assert warning.detail == "Thing: app.a, app.b"
    assert warning.path is None


def test_external_and_module_imports_are_untouched() -> None:
    edges = [
        ImportEdge("app.use", "app", True, "Engine", 1),
        ImportEdge("app.use", "app", False, None, 2),
    ]
    result = single_module_result(edges, [ReExport("app", "app.core", "Engine")])
    assert resolve_indirection(result).modules[0].imports == edges


def test_edge_resolving_to_its_own_source_is_dropped() -> None:
    edges = [ImportEdge("app.use", "app", False, "Helper", 1)]
    result = single_module_result(edges, [ReExport("app", "app.use", "Helper")])
    assert resolve_indirection(result).modules[0].imports == []


def test_input_is_not_mutated(reexport_chain: Path) -> None:
    result = parse_fixture(reexport_chain)
    snapshot = copy.deepcopy(result)
    resolve_indirection(result)
    assert result == snapshot


def test_cycle_warning_is_identical_from_any_entry_point() -> None:
    index = build_reexport_index(
        [
            ReExport("app", "app.a", "Thing"),
            ReExport("app.a", "app.b", "Thing"),
            ReExport("app.b", "app.a", "Thing"),
        ]
    )
    warnings = {resolve_target(m, "Thing", index)[1][0] for m in ("app", "app.a", "app.b")}
    assert len(warnings) == 1
    assert next(iter(warnings)).detail == "Thing: app.a, app.b"


def test_follows_multilevel_chain() -> None:
    index = build_reexport_index(
        [
            ReExport("app", "app.core", "Engine"),
            ReExport("app.core", "app.core.impl.engine", "Engine"),
        ]
    )
    assert resolve_target("app", "Engine", index) == ("app.core.impl.engine", [])


def test_module_import_is_not_resolved() -> None:
    index = build_reexport_index([ReExport("app", "app.core", "Engine")])
    assert resolve_target("app", None, index) == ("app", [])


def test_cycle_degrades_with_warning() -> None:
    index = build_reexport_index(
        [ReExport("app.a", "app.b", "Thing"), ReExport("app.b", "app.a", "Thing")]
    )
    target, warnings = resolve_target("app.a", "Thing", index)
    assert target == "app.a"
    assert [w.code for w in warnings] == [WarningCode.REEXPORT_CYCLE]


def test_depth_limit_degrades_with_warning() -> None:
    chain = [ReExport(f"m{i}", f"m{i + 1}", "X") for i in range(MAX_RESOLUTION_DEPTH + 5)]
    target, warnings = resolve_target("m0", "X", build_reexport_index(chain))
    assert target == f"m{MAX_RESOLUTION_DEPTH}"
    assert [w.code for w in warnings] == [WarningCode.REEXPORT_DEPTH_EXCEEDED]
