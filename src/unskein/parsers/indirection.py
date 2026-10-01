"""Resolve imports that go through re-exporting facades to the defining module."""

from dataclasses import replace

from unskein.parsers.models import ImportEdge, ParseResult, ParseWarning, ReExport, WarningCode

MAX_RESOLUTION_DEPTH = 10

ReExportIndex = dict[tuple[str, str], str]


def build_reexport_index(re_exports: list[ReExport]) -> ReExportIndex:
    """Index re-exports by (exporting module, symbol) for constant-time lookup.

    When a facade exposes the same symbol more than once (typically a
    ``try/except ImportError`` fallback), the first one in the code wins.

    Args:
        re_exports: Re-exports detected by the parser, in code order.

    Returns:
        A mapping from (exporting module, symbol) to the module the symbol comes from.
    """
    index: ReExportIndex = {}
    for re_export in re_exports:
        index.setdefault(
            (re_export.exporting_module, re_export.symbol_name), re_export.original_module
        )
    return index


def resolve_target(
    module: str,
    symbol: str | None,
    index: ReExportIndex,
    path: list[str] | None = None,
) -> tuple[str, list[ParseWarning]]:
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
        # Canonical (sorted) members so every entry point into the cycle yields the same warning.
        members = ", ".join(sorted(path[path.index(module) :]))
        detail = f"{symbol}: {members}"
        return module, [ParseWarning(WarningCode.REEXPORT_CYCLE, None, None, detail)]
    if len(path) >= MAX_RESOLUTION_DEPTH:
        detail = f"{symbol}: {module}"
        return module, [ParseWarning(WarningCode.REEXPORT_DEPTH_EXCEEDED, None, None, detail)]

    path.append(module)
    return resolve_target(index[(module, symbol)], symbol, index, path)


def resolve_access(
    package: str, chain: str, *, modules: frozenset[str], index: ReExportIndex
) -> tuple[str, str | None, list[ParseWarning]]:
    """Follow an attribute chain read through a package down to the module that defines it.

    The longest prefix of the chain that names project submodules is walked first;
    the attribute after it is a symbol of the last module reached, followed through
    its re-exports.

    Args:
        package: Package the name is bound to.
        chain: Dotted attributes read through it, e.g. ``algorithms.shortest_path``.
        modules: Names of the project modules.
        index: Re-export index built by `build_reexport_index`.

    Returns:
        The defining module, the symbol (None when the chain ends at a module) and the
        warnings produced while resolving.
    """
    parts = chain.split(".")
    module = package
    position = 0
    while position < len(parts) and f"{module}.{parts[position]}" in modules:
        module = f"{module}.{parts[position]}"
        position += 1
    if position == len(parts):
        return module, None, []
    symbol = parts[position]
    target, warnings = resolve_target(module, symbol, index)
    return target, symbol, warnings


def expand_package_access(
    edge: ImportEdge, *, modules: frozenset[str], index: ReExportIndex
) -> tuple[list[ImportEdge], list[ParseWarning]]:
    """Replace the import of a package by one edge per module its attributes come from.

    Unresolvable uses keep the edge to the package, so no dependency is ever lost:
    the name is used by itself, or no attribute of it is read.

    Args:
        edge: Internal whole-module import edge.
        modules: Names of the project modules.
        index: Re-export index built by `build_reexport_index`.

    Returns:
        The replacement edges, one per distinct defining module and in module order
        (an edge back to the importing module is dropped), and the warnings produced.
    """
    if edge.escapes or not edge.accessed:
        return [edge], []
    warnings: list[ParseWarning] = []
    symbols: dict[str, set[str | None]] = {}
    for chain in edge.accessed:
        target, symbol, chain_warnings = resolve_access(
            edge.target, chain, modules=modules, index=index
        )
        warnings += chain_warnings
        if target != edge.source:
            symbols.setdefault(target, set()).add(symbol)
    expanded = [
        replace(
            edge,
            target=target,
            symbol_name=next(iter(found)) if len(found) == 1 else None,
            accessed=(),
            escapes=False,
        )
        for target, found in sorted(symbols.items())
    ]
    return expanded, warnings


def resolve_indirection(result: ParseResult) -> ParseResult:
    """Point internal symbol imports at the defining module.

    Whole-module imports of a package are replaced by one edge per module their
    attributes come from (see `expand_package_access`); external imports are kept
    as they are; edges that resolve back to their own source are dropped; warnings
    are deduplicated. The input is not mutated.

    Args:
        result: Parse result whose imports should be resolved.

    Returns:
        A new parse result with resolved import targets.
    """
    index = build_reexport_index(result.re_exports)
    module_names = frozenset(module.name for module in result.modules)
    warnings = dict.fromkeys(result.warnings)
    modules = []
    for module in result.modules:
        imports = []
        for edge in module.imports:
            if edge.is_external:
                imports.append(edge)
                continue
            if edge.symbol_name is None:
                expanded, edge_warnings = expand_package_access(
                    edge, modules=module_names, index=index
                )
                imports.extend(expanded)
                warnings.update(dict.fromkeys(edge_warnings))
                continue
            target, edge_warnings = resolve_target(edge.target, edge.symbol_name, index)
            warnings.update(dict.fromkeys(edge_warnings))
            if target != edge.source:
                imports.append(replace(edge, target=target))
        modules.append(replace(module, imports=imports))
    return replace(result, modules=modules, warnings=list(warnings))
