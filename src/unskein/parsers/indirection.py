"""Resolve imports that go through re-exporting facades to the defining module."""

from dataclasses import replace

from unskein.parsers.models import ParseResult, ReExport

MAX_RESOLUTION_DEPTH = 10

ReExportIndex = dict[tuple[str, str], str]


def build_reexport_index(re_exports: list[ReExport]) -> ReExportIndex:
    """Index re-exports by (exporting module, symbol) for constant-time lookup.

    Args:
        re_exports: Re-exports detected by the parser.

    Returns:
        A mapping from (exporting module, symbol) to the module the symbol comes from.
    """
    return {(re.exporting_module, re.symbol_name): re.original_module for re in re_exports}


def resolve_target(
    module: str,
    symbol: str | None,
    index: ReExportIndex,
    path: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Follow the re-export chain of a symbol until the module that defines it.

    Cycles and chains longer than MAX_RESOLUTION_DEPTH stop the resolution with a
    warning instead of failing.

    Args:
        module: Module the symbol is imported from.
        symbol: Imported symbol, or None for a whole-module import (never resolved).
        index: Re-export index built by `build_reexport_index`.
        path: Modules already visited in this chain; callers leave it as None.

    Returns:
        The resolved module and the warnings produced while resolving.
    """
    if path is None:
        path = []

    if symbol is None or (module, symbol) not in index:
        return module, []
    if module in path:
        # Canonical (sorted) members so every entry point into the cycle yields the same text.
        members = ", ".join(f"'{m}'" for m in sorted(path[path.index(module) :]))
        return module, [f"Re-export cycle for '{symbol}' between {members}, stopping resolution"]
    if len(path) >= MAX_RESOLUTION_DEPTH:
        return module, [f"Max re-export depth exceeded for '{symbol}' at '{module}'"]

    path.append(module)
    return resolve_target(index[(module, symbol)], symbol, index, path)


def resolve_indirection(result: ParseResult) -> ParseResult:
    """Point internal symbol imports at the defining module.

    External and whole-module imports are kept as they are; edges that resolve
    back to their own source are dropped; warnings are deduplicated. The input is
    not mutated.

    Args:
        result: Parse result whose imports should be resolved.

    Returns:
        A new parse result with resolved import targets.
    """
    index = build_reexport_index(result.re_exports)
    warnings = dict.fromkeys(result.warnings)
    modules = []
    for module in result.modules:
        imports = []
        for edge in module.imports:
            if edge.is_external or edge.symbol_name is None:
                imports.append(edge)
                continue
            target, edge_warnings = resolve_target(edge.target, edge.symbol_name, index)
            warnings.update(dict.fromkeys(edge_warnings))
            if target != edge.source:
                imports.append(replace(edge, target=target))
        modules.append(replace(module, imports=imports))
    return replace(result, modules=modules, warnings=list(warnings))
