"""Resolve imports that go through re-exporting facades to the defining module."""

from collections.abc import Mapping, Sequence
from dataclasses import replace

from unskein.parsers.models import (
    STAR_EXPORT,
    ImportEdge,
    ModuleInfo,
    ParseResult,
    ParseWarning,
    ReExport,
    WarningCode,
)

MAX_RESOLUTION_DEPTH = 10

ReExportIndex = dict[tuple[str, str], str]
StarNames = dict[tuple[str, str], tuple[str, ...]]


def build_reexport_index(
    re_exports: list[ReExport], star_names: Mapping[tuple[str, str], tuple[str, ...]] | None = None
) -> ReExportIndex:
    """Index re-exports by (exporting module, symbol) for constant-time lookup.

    When a facade exposes the same symbol more than once (typically a
    ``try/except ImportError`` fallback, or an explicit re-export and a star
    import), the first one in the code wins. A star re-export stands for every
    name it brings into the facade.

    Args:
        re_exports: Re-exports detected by the parser, in code order.
        star_names: Names each (facade, star-imported module) pair brings in (see
            `star_exports`).

    Returns:
        A mapping from (exporting module, symbol) to the module the symbol comes from.
    """
    star_names = star_names or {}
    index: ReExportIndex = {}
    for re_export in re_exports:
        exporting, original = re_export.exporting_module, re_export.original_module
        if re_export.symbol_name == STAR_EXPORT:
            for name in star_names.get((exporting, original), ()):
                index.setdefault((exporting, name), original)
        else:
            index.setdefault((exporting, re_export.symbol_name), original)
    return index


def star_exports(modules: Sequence[ModuleInfo], re_exports: Sequence[ReExport]) -> StarNames:
    """Return, for each star import in a facade, the names it brings into the facade.

    A module without a literal ``__all__`` also passes on what it star-imports
    itself, as Python does. Names the facade binds itself (definitions, explicit
    imports) are never taken from a star.

    Args:
        modules: Parsed project modules.
        re_exports: Re-exports detected by the parser, star ones included.

    Returns:
        Sorted names per (facade, star-imported module) pair.
    """
    by_name = {module.name: module for module in modules}
    stars: dict[str, list[str]] = {}
    for re_export in re_exports:
        if re_export.symbol_name == STAR_EXPORT:
            stars.setdefault(re_export.exporting_module, []).append(re_export.original_module)
    result: StarNames = {}
    for facade, sources in sorted(stars.items()):
        own = set(by_name[facade].bound_names) if facade in by_name else set()
        for source in sources:
            names = _names_through_stars(source, by_name, stars)
            result[facade, source] = tuple(name for name in names if name not in own)
    return result


def _names_through_stars(
    source: str, by_name: Mapping[str, ModuleInfo], stars: Mapping[str, list[str]]
) -> tuple[str, ...]:
    """Collect the names a star import of one module brings in, following nested stars.

    Args:
        source: Star-imported module.
        by_name: Parsed modules by name.
        stars: Star-imported modules per facade.

    Returns:
        The names, sorted; cycles of star imports are visited once.
    """
    names: set[str] = set()
    seen = {source}
    pending = [source]
    while pending:
        module = by_name.get(pending.pop())
        if module is None:
            continue
        names.update(module.public_names)
        if module.declares_all:
            continue
        for nested in stars.get(module.name, []):
            if nested not in seen:
                seen.add(nested)
                pending.append(nested)
    return tuple(sorted(names))


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


def walk_submodules(package: str, chain: str, modules: frozenset[str]) -> tuple[str, str | None]:
    """Follow an attribute chain down the project submodules it names.

    Args:
        package: Module the chain is read through.
        chain: Dotted attributes, e.g. ``algorithms.shortest_path``.
        modules: Names of the project modules.

    Returns:
        The deepest submodule reached and the attribute read from it, or None when the
        chain ends at a module.
    """
    parts = chain.split(".")
    module = package
    position = 0
    while position < len(parts) and f"{module}.{parts[position]}" in modules:
        module = f"{module}.{parts[position]}"
        position += 1
    return module, parts[position] if position < len(parts) else None


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
    module, symbol = walk_submodules(package, chain, modules)
    if symbol is None:
        return module, None, []
    target, warnings = resolve_target(module, symbol, index)
    return target, symbol, warnings


def expand_package_access(
    edge: ImportEdge, *, modules: frozenset[str], index: ReExportIndex
) -> tuple[list[ImportEdge], list[ParseWarning]]:
    """Replace the import of a package by one edge per module its attributes come from.

    Uses that cannot be followed keep the edge to the package: the name is used by
    itself, or no attribute of it is read. Chains that resolve to the importing module
    itself add no edge.

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
    index = build_reexport_index(result.re_exports, star_exports(result.modules, result.re_exports))
    # Namespace packages have no file, but chains walk through them to their submodules.
    module_names = frozenset(module.name for module in result.modules) | frozenset(
        result.namespaces
    )
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
