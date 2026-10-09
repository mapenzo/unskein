"""Resolve imports that go through re-exporting facades to the defining module."""

from collections.abc import Mapping, Sequence
from dataclasses import replace

import networkx as nx

from unskein.parsers.discovery import parse_source
from unskein.parsers.exports import module_surface
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
PACKAGE_INIT_FILE = "__init__.py"
PRIVATE_PREFIX = "_"
NAME_SEPARATOR = "."
# A facade's star re-export has no line of its own in ``star_imports``.
FACADE_LINE = 0

# A star statement: (line, star-imported module).
Star = tuple[int, str]

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


def guarded_reexports(
    re_exports: list[ReExport], star_names: Mapping[tuple[str, str], tuple[str, ...]] | None = None
) -> frozenset[tuple[str, str]]:
    """Return the (facade, symbol) pairs whose winning re-export is guarded.

    The same first-wins rule as `build_reexport_index` decides which re-export counts.

    Args:
        re_exports: Re-exports detected by the parser, in code order.
        star_names: Names each (facade, star-imported module) pair brings in.

    Returns:
        The pairs the facade imports inside a ``try`` or ``suppress`` for import errors.
    """
    star_names = star_names or {}
    winners: dict[tuple[str, str], bool] = {}
    for re_export in re_exports:
        exporting, original = re_export.exporting_module, re_export.original_module
        if re_export.symbol_name == STAR_EXPORT:
            for name in star_names.get((exporting, original), ()):
                winners.setdefault((exporting, name), re_export.is_guarded)
        else:
            winners.setdefault((exporting, re_export.symbol_name), re_export.is_guarded)
    return frozenset(pair for pair, is_guarded in winners.items() if is_guarded)


def passes_guard(
    module: str, symbol: str | None, index: ReExportIndex, guarded: frozenset[tuple[str, str]]
) -> bool:
    """Tell whether a symbol's re-export chain goes through a guarded re-export.

    A facade that imports the symbol in a ``try`` for import errors falls back when the
    module is missing, so its users do not fail either.

    Args:
        module: Module the symbol is imported from.
        symbol: Imported symbol, or None for a whole-module import.
        index: Re-export index built by `build_reexport_index`.
        guarded: Guarded re-exports, from `guarded_reexports`.

    Returns:
        True when some step of the chain is guarded.
    """
    visited: set[str] = set()
    while symbol is not None and (module, symbol) in index and module not in visited:
        if (module, symbol) in guarded:
            return True
        visited.add(module)
        if len(visited) > MAX_RESOLUTION_DEPTH:
            return False
        module = index[(module, symbol)]
    return False


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


def star_imports(
    modules: Sequence[ModuleInfo], re_exports: Sequence[ReExport]
) -> dict[str, list[Star]]:
    """Return the star imports of every module, facades included, in code order.

    Args:
        modules: Parsed project modules.
        re_exports: Re-exports detected by the parser.

    Returns:
        Each module's star statements; facade re-exports carry ``FACADE_LINE``.
    """
    stars: dict[str, list[Star]] = {}
    for re_export in re_exports:
        if re_export.symbol_name == STAR_EXPORT:
            stars.setdefault(re_export.exporting_module, []).append(
                (FACADE_LINE, re_export.original_module)
            )
    for module in modules:
        for line, base in module.stars.statements:
            if base != module.name:
                stars.setdefault(module.name, []).append((line, base))
    return stars


def _submodules_bound(module: ModuleInfo) -> set[str]:
    """Return the submodules a package ``__init__`` binds by importing them.

    Importing ``pkg.sub`` (``from .sub import f`` included) sets ``sub`` on the package, so
    ``from pkg import *`` brings it when the package has no ``__all__``.

    Args:
        module: A parsed module.

    Returns:
        The public submodule names, empty for a module that is not a package.
    """
    if module.file_path.name != PACKAGE_INIT_FILE:
        return set()
    start = f"{module.name}{NAME_SEPARATOR}"
    found = set()
    for edge in module.imports:
        if not edge.is_external and edge.target.startswith(start):
            name = edge.target[len(start) :].split(NAME_SEPARATOR)[0]
            if not name.startswith(PRIVATE_PREFIX):
                found.add(name)
    return found


def wildcard_names(
    base: str, by_name: Mapping[str, ModuleInfo], stars: Mapping[str, list[Star]]
) -> frozenset[str] | None:
    """Return the names ``from base import *`` brings, following nested star imports.

    Args:
        base: Star-imported module.
        by_name: Parsed modules by name.
        stars: Star imports of every module (``star_imports``).

    Returns:
        The names (those that may be unbound included, see ``wildcard_conditional``); None
        when some module on the way was not parsed, computes ``__all__`` or brings names
        nobody can list.
    """
    names: set[str] = set()
    seen = {base}
    pending = [base]
    while pending:
        module = by_name.get(pending.pop())
        if module is None or module.surface.dynamic_all or module.surface.uncertain:
            return None
        names.update(module.public_names)
        names.update(module.surface.conditional)
        if module.declares_all:
            continue
        names.update(_submodules_bound(module))
        for _, nested in stars.get(module.name, []):
            if nested not in seen:
                seen.add(nested)
                pending.append(nested)
    return frozenset(names)


def star_cycles(stars: Mapping[str, list[Star]]) -> frozenset[tuple[str, str]]:
    """Return the star imports that sit in a cycle of star imports, as (importer, module).

    In a cycle one module runs ``from x import *`` while ``x`` is still being imported, so
    what the star brings depends on import order and cannot be read from the source.

    Args:
        stars: Star imports of every module (``star_imports``).

    Returns:
        The (importer, star-imported module) pairs inside a cycle.
    """
    graph = nx.DiGraph((importer, base) for importer, items in stars.items() for _, base in items)
    pairs: set[tuple[str, str]] = set()
    for component in nx.strongly_connected_components(graph):
        if len(component) > 1:
            pairs.update(edge for edge in graph.subgraph(component).edges)
    return frozenset(pairs)


def wildcard_conditional(
    base: str, by_name: Mapping[str, ModuleInfo], stars: Mapping[str, list[Star]]
) -> frozenset[str]:
    """Return the names ``from base import *`` may bring that may be unbound when it runs.

    Args:
        base: Star-imported module.
        by_name: Parsed modules by name.
        stars: Star imports of every module (``star_imports``).

    Returns:
        The conditional names of every module the star reaches.
    """
    names: set[str] = set()
    seen = {base}
    pending = [base]
    while pending:
        module = by_name.get(pending.pop())
        if module is None:
            continue
        names.update(module.surface.conditional)
        if module.declares_all:
            continue
        for _, nested in stars.get(module.name, []):
            if nested not in seen:
                seen.add(nested)
                pending.append(nested)
    return frozenset(names)


def _with_surfaces(result: ParseResult, stars: Mapping[str, list[Star]]) -> ParseResult:
    """Complete the star surface of every module something star-imports.

    Reads those sources again: the surface is only needed for them, and computing it while
    parsing every file would cost more than the whole rule.

    Args:
        result: Parse result.
        stars: Star imports of every module (``star_imports``).

    Returns:
        The result with ``ModuleInfo.surface`` complete for star-imported modules.
    """
    bases = {base for statements in stars.values() for _, base in statements}
    modules = []
    for module in result.modules:
        if module.name in bases:
            tree = parse_source(module.file_path, None)
            if tree is None:
                surface = replace(module.surface, uncertain=True)
            else:
                source = module.file_path.read_text(errors="replace")
                conditional, uncertain = module_surface(tree, source)
                surface = replace(
                    module.surface,
                    uncertain=module.surface.uncertain or uncertain,
                    conditional=conditional,
                )
            module = replace(module, surface=surface)
        modules.append(module)
    return replace(result, modules=modules)


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
    edge: ImportEdge,
    *,
    modules: frozenset[str],
    index: ReExportIndex,
    guarded: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[list[ImportEdge], list[ParseWarning]]:
    """Replace the import of a package by one edge per module its attributes come from.

    Uses that cannot be followed keep the edge to the package: the name is used by
    itself, or no attribute of it is read. Chains that resolve to the importing module
    itself add no edge.

    Args:
        edge: Internal whole-module import edge.
        modules: Names of the project modules.
        index: Re-export index built by `build_reexport_index`.
        guarded: Guarded re-exports: an edge whose every chain goes through one is guarded.

    Returns:
        The replacement edges, one per distinct defining module and in module order
        (an edge back to the importing module is dropped), and the warnings produced.
    """
    if edge.escapes or not edge.accessed:
        return [edge], []
    warnings: list[ParseWarning] = []
    symbols: dict[str, set[str | None]] = {}
    unguarded: set[str] = set()
    for chain in edge.accessed:
        target, symbol, chain_warnings = resolve_access(
            edge.target, chain, modules=modules, index=index
        )
        warnings += chain_warnings
        if target != edge.source:
            symbols.setdefault(target, set()).add(symbol)
            if not passes_guard(*walk_submodules(edge.target, chain, modules), index, guarded):
                unguarded.add(target)
    expanded = [
        replace(
            edge,
            target=target,
            symbol_name=next(iter(found)) if len(found) == 1 else None,
            accessed=(),
            escapes=False,
            is_guarded=edge.is_guarded or target not in unguarded,
        )
        for target, found in sorted(symbols.items())
    ]
    return expanded, warnings


def resolve_indirection(result: ParseResult) -> ParseResult:
    """Point internal symbol imports at the defining module.

    Whole-module imports of a package are replaced by one edge per module their
    attributes come from (see `expand_package_access`); external imports are kept
    as they are; edges that resolve back to their own source are dropped; warnings
    are deduplicated. Star imports whose names cannot be known (module not parsed,
    computed ``__all__``, a cycle of star imports) get a ``STAR_IMPORT`` warning. The
    input is not mutated.

    Args:
        result: Parse result whose imports should be resolved.

    Returns:
        A new parse result with resolved import targets.
    """
    stars = star_exports(result.modules, result.re_exports)
    index = build_reexport_index(result.re_exports, stars)
    guarded = guarded_reexports(result.re_exports, stars)
    # Virtual modules have no file, but chains walk through them to their submodules.
    module_names = frozenset(module.name for module in result.modules) | frozenset(result.virtual)
    warnings = dict.fromkeys(result.warnings)
    every_star = star_imports(result.modules, result.re_exports)
    result = _with_surfaces(result, every_star)
    by_name = {module.name: module for module in result.modules}
    cycles = star_cycles(every_star)
    for module in result.modules:
        for line, base in module.stars.statements:
            unknown = (module.name, base) in cycles or (
                wildcard_names(base, by_name, every_star) is None
            )
            if base != module.name and unknown:
                warning = ParseWarning(WarningCode.STAR_IMPORT, module.file_path, line, base)
                warnings[warning] = None
    modules = []
    for module in result.modules:
        imports = []
        for edge in module.imports:
            if edge.is_external:
                imports.append(edge)
                continue
            if edge.symbol_name is None:
                expanded, edge_warnings = expand_package_access(
                    edge, modules=module_names, index=index, guarded=guarded
                )
                imports.extend(expanded)
                warnings.update(dict.fromkeys(edge_warnings))
                continue
            target, edge_warnings = resolve_target(edge.target, edge.symbol_name, index)
            warnings.update(dict.fromkeys(edge_warnings))
            if target != edge.source:
                is_guarded = edge.is_guarded or passes_guard(
                    edge.target, edge.symbol_name, index, guarded
                )
                imports.append(replace(edge, target=target, is_guarded=is_guarded))
        modules.append(replace(module, imports=imports))
    return replace(result, modules=modules, warnings=list(warnings))
