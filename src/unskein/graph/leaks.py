"""Rule 13: code outside a package imports what the package keeps internal."""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import networkx as nx

from unskein.config import ApiContract
from unskein.graph.findings import Evidence, Finding, FindingKind
from unskein.parsers.indirection import (
    ReExportIndex,
    build_reexport_index,
    guarded_reexports,
    passes_guard,
    resolve_target,
    star_exports,
)
from unskein.parsers.layout import relative_path
from unskein.parsers.models import STAR_EXPORT, ImportEdge, ModuleInfo, ParseResult

MAX_FIXES_SHOWN = 5
FIX_SEPARATOR = "; "
ROOT_SEPARATOR = "; "
ROOT_COUNT_SEPARATOR = " "
SEGMENT_SEPARATOR = "."
LINE_SEPARATOR = ":"
PRIVATE_PREFIX = "_"
DUNDER_AFFIX = "__"


class ApiVerdict(StrEnum):
    """What the contract and the naming convention say about a module.

    Attributes:
        DECLARED_INTERNAL: The longest matching ``[api]`` prefix is in ``internal``.
        DECLARED_PUBLIC: The longest matching ``[api]`` prefix is in ``public``.
        CONVENTION_INTERNAL: No prefix matches and a name segment starts with ``_``.
        PUBLIC: Neither the contract nor the convention marks it internal.
    """

    DECLARED_INTERNAL = "declared_internal"
    DECLARED_PUBLIC = "declared_public"
    CONVENTION_INTERNAL = "convention_internal"
    PUBLIC = "public"


class LeakKind(StrEnum):
    """Which kind of leak a module is the target of.

    Attributes:
        INTERNAL: The module is internal and outside code imports it.
        BYPASS: The module is public, but an ancestor package offers the same name.
    """

    INTERNAL = "internal"
    BYPASS = "bypass"


class LeakReason(StrEnum):
    """Why a module counts as a leak target.

    Attributes:
        DECLARED: ``[api]`` declares it internal.
        CONVENTION: A segment of its name starts with an underscore.
        FACADE: An ancestor package re-exports the imported name.
    """

    DECLARED = "declared"
    CONVENTION = "convention"
    FACADE = "facade"


class LeakAction(StrEnum):
    """What the report tells the user to do with one statement.

    Attributes:
        FACADE_IMPORT: Import the name from the ancestor facade instead.
        NO_FIX: No fix is proven safe; the reason says why.
    """

    FACADE_IMPORT = "facade_import"
    NO_FIX = "no_fix"


class LeakNoFix(StrEnum):
    """Why a statement has no fix.

    Attributes:
        NO_PUBLIC_PATH: No package offers the name; the owner has to decide.
        NOT_ANCESTOR: Only a package that is not an ancestor offers it.
        CYCLE: The facade imports the consumer when it loads.
        GUARDED: The facade imports the name inside a ``try`` for import errors.
        REBOUND: The facade binds the name more than once.
        MODULE_IMPORT: The statement imports a module, not a name.
    """

    NO_PUBLIC_PATH = "no_public_path"
    NOT_ANCESTOR = "not_ancestor"
    CYCLE = "cycle"
    GUARDED = "guarded"
    REBOUND = "rebound"
    MODULE_IMPORT = "module_import"


@dataclass(frozen=True, slots=True)
class LeakFix:
    """The fix, or the reason for none, of one import statement.

    Attributes:
        location: ``path:line`` of the statement, relative to the project root.
        importer: Module that holds the statement.
        action: What to do with it.
        symbol: Imported name; None for a whole-module import.
        alias: Name the statement binds when it differs from ``symbol``.
        facade: Package to import the name from; set with ``FACADE_IMPORT``.
        reason: Why there is no fix; set with ``NO_FIX``.
    """

    location: str
    importer: str
    action: LeakAction
    symbol: str | None
    alias: str | None = None
    facade: str | None = None
    reason: LeakNoFix | None = None


@dataclass(frozen=True, slots=True)
class LeakModule:
    """One module outside code reaches into, with every statement that does.

    Attributes:
        name: The module as the statements wrote it.
        kind: Whether it is internal or only bypassed.
        reason: Why it counts.
        consumers: Distinct importing modules.
        roots: Statements per importing top-level package, most first.
        fixes: One entry per statement, in file order.
        fixed: How many statements have a proven fix.
    """

    name: str
    kind: LeakKind
    reason: LeakReason
    consumers: int
    roots: tuple[tuple[str, int], ...]
    fixes: tuple[LeakFix, ...]
    fixed: int


@dataclass(frozen=True, slots=True)
class _Use:
    """An import statement from outside a package into one of its modules.

    Attributes:
        importer: The module that holds the statement.
        edge: The import edge.
        written: Module the statement named.
        facades: Public ancestor packages that offer the imported name.
    """

    importer: ModuleInfo
    edge: ImportEdge
    written: str
    facades: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Context:
    """What proving a fix needs, computed once per project.

    Attributes:
        modules: Parsed modules by name.
        names: Every project module name, virtual ones included.
        root: Project root, for relative paths.
        api: The declared contract.
        index: Re-export index.
        guarded: Guarded re-exports.
        offers: Packages that offer each (defining module, name), nearest ancestor first.
        rebound: (facade, name) pairs the facade binds more than once.
        import_graph: Dependencies that exist when modules are imported.
        reach: Cache of what each facade imports when it loads.
    """

    modules: Mapping[str, ModuleInfo]
    names: frozenset[str]
    root: Path | None
    api: ApiContract
    index: ReExportIndex
    guarded: frozenset[tuple[str, str]]
    offers: Mapping[tuple[str, str], tuple[str, ...]]
    rebound: frozenset[tuple[str, str]]
    import_graph: nx.DiGraph
    reach: dict[str, frozenset[str]] = field(default_factory=dict)


def _covers(prefix: str, module: str) -> bool:
    """Tell whether a module is the prefix or lies under it, by whole segments.

    Args:
        prefix: A declared module prefix.
        module: A module name.

    Returns:
        True when ``module`` is ``prefix`` or ``prefix.<something>``.
    """
    return module == prefix or module.startswith(prefix + SEGMENT_SEPARATOR)


def _is_private(segment: str) -> bool:
    """Tell whether a name segment is private by convention.

    Args:
        segment: One dotted segment of a module name.

    Returns:
        True when it starts with an underscore and is not a dunder.
    """
    is_dunder = segment.startswith(DUNDER_AFFIX) and segment.endswith(DUNDER_AFFIX)
    return segment.startswith(PRIVATE_PREFIX) and not is_dunder


def classify_module(module: str, api: ApiContract) -> ApiVerdict:
    """Decide whether a module is internal: the contract first, then the convention.

    Args:
        module: Dotted module name.
        api: The declared contract.

    Returns:
        The verdict; the longest matching prefix of ``api`` wins.
    """
    best = -1
    verdict: ApiVerdict | None = None
    for prefixes, declared in (
        (api.public, ApiVerdict.DECLARED_PUBLIC),
        (api.internal, ApiVerdict.DECLARED_INTERNAL),
    ):
        for prefix in prefixes:
            if _covers(prefix, module) and len(prefix) > best:
                best, verdict = len(prefix), declared
    if verdict is not None:
        return verdict
    if any(_is_private(segment) for segment in module.split(SEGMENT_SEPARATOR)):
        return ApiVerdict.CONVENTION_INTERNAL
    return ApiVerdict.PUBLIC


def _root_of(module: str) -> str:
    """Return the top-level package of a module name.

    Args:
        module: Dotted module name.

    Returns:
        Its first segment.
    """
    return module.partition(SEGMENT_SEPARATOR)[0]


def _is_public(module: str, api: ApiContract) -> bool:
    """Tell whether a package may be recommended as the place to import from.

    Args:
        module: Dotted module name.
        api: The declared contract.

    Returns:
        True unless the contract or the convention marks it internal.
    """
    return classify_module(module, api) in (ApiVerdict.PUBLIC, ApiVerdict.DECLARED_PUBLIC)


def _offers(index: ReExportIndex) -> dict[tuple[str, str], tuple[str, ...]]:
    """Map each (defining module, name) to the packages that re-export it.

    Args:
        index: Re-export index.

    Returns:
        For every pair, its exporters with the longest (nearest) name first.
    """
    found: dict[tuple[str, str], list[str]] = defaultdict(list)
    for exporter, symbol in index:
        origin, _ = resolve_target(exporter, symbol, index)
        if origin != exporter:
            found[(origin, symbol)].append(exporter)
    return {
        pair: tuple(sorted(names, key=lambda name: (-len(name), name)))
        for pair, names in found.items()
    }


def _rebound(result: ParseResult) -> frozenset[tuple[str, str]]:
    """Find the (facade, name) pairs a facade binds more than once.

    Args:
        result: Parsed project.

    Returns:
        Pairs re-exported from two different modules, or re-exported and also defined.
    """
    origins: dict[tuple[str, str], set[str]] = defaultdict(set)
    for re_export in result.re_exports:
        if re_export.symbol_name != STAR_EXPORT:
            pair = (re_export.exporting_module, re_export.symbol_name)
            origins[pair].add(re_export.original_module)
    pairs = {pair for pair, found in origins.items() if len(found) > 1}
    for module in result.modules:
        pairs.update(
            (module.name, name) for name in module.defined_names if (module.name, name) in origins
        )
    return frozenset(pairs)


def _context(result: ParseResult, import_graph: nx.DiGraph, api: ApiContract) -> _Context:
    """Build the shared context of a project.

    Args:
        result: Parsed project, re-exports resolved.
        import_graph: Dependencies that exist when modules are imported.
        api: The declared contract.

    Returns:
        The context.
    """
    stars = star_exports(result.modules, result.re_exports)
    index = build_reexport_index(result.re_exports, stars)
    return _Context(
        modules={module.name: module for module in result.modules},
        names=frozenset(module.name for module in result.modules) | frozenset(result.virtual),
        root=result.project_root,
        api=api,
        index=index,
        guarded=guarded_reexports(result.re_exports, stars),
        offers=_offers(index),
        rebound=_rebound(result),
        import_graph=import_graph,
    )


def _is_consumer(importer: ModuleInfo, written: str, context: _Context) -> bool:
    """Tell whether an importer is outside the package that owns a module.

    Args:
        importer: Module that holds the statement.
        written: Module the statement named.
        context: Shared context.

    Returns:
        True when the top-level package differs, or the named distributions differ.
    """
    if _root_of(importer.name) != _root_of(written):
        return True
    owner = context.modules.get(written)
    return (
        owner is not None
        and importer.distribution is not None
        and owner.distribution is not None
        and importer.distribution != owner.distribution
    )


def _facades(edge: ImportEdge, written: str, context: _Context) -> tuple[str, ...]:
    """List the public ancestor packages of a module that offer the imported name.

    Args:
        edge: The import edge.
        written: Module the statement named.
        context: Shared context.

    Returns:
        The packages, nearest first; empty for a whole-module import.
    """
    if edge.symbol_name is None:
        return ()
    exporters = context.offers.get((edge.target, edge.symbol_name), ())
    return tuple(
        exporter
        for exporter in exporters
        if written.startswith(exporter + SEGMENT_SEPARATOR) and _is_public(exporter, context.api)
    )


def _use(importer: ModuleInfo, edge: ImportEdge, context: _Context) -> _Use | None:
    """Turn an import edge into a leak use, or None when it is not one.

    Args:
        importer: Module that holds the statement.
        edge: One of its import edges.
        context: Shared context.

    Returns:
        The use when an outside module imports an internal module or bypasses a facade.
    """
    if edge.is_external or edge.requested is not None or edge.source == edge.target:
        return None
    written = edge.written or edge.target
    if written not in context.names or not _is_consumer(importer, written, context):
        return None
    verdict = classify_module(written, context.api)
    if verdict is ApiVerdict.DECLARED_PUBLIC:
        return None
    facades = _facades(edge, written, context)
    if verdict is ApiVerdict.PUBLIC and not facades:
        return None
    return _Use(importer, edge, written, facades)


def _reachable(facade: str, context: _Context) -> frozenset[str]:
    """Return the modules a facade imports when it loads, directly or not.

    Args:
        facade: Package whose ``__init__`` runs.
        context: Shared context; caches the answer.

    Returns:
        The modules reachable through import-time dependencies.
    """
    if facade not in context.reach:
        graph = context.import_graph
        reachable = nx.descendants(graph, facade) if facade in graph else ()
        context.reach[facade] = frozenset(reachable)
    return context.reach[facade]


def _location(use: _Use, context: _Context) -> str:
    """Return ``path:line`` of the statement.

    Args:
        use: The use.
        context: Shared context.

    Returns:
        The location relative to the project root.
    """
    path = relative_path(use.importer.file_path, context.root)
    return f"{path}{LINE_SEPARATOR}{use.edge.line_number}"


def _no_fix(use: _Use, context: _Context, reason: LeakNoFix) -> LeakFix:
    """Build the entry of a statement that has no proven fix.

    Args:
        use: The use.
        context: Shared context.
        reason: Why.

    Returns:
        The entry.
    """
    return LeakFix(
        _location(use, context),
        use.importer.name,
        LeakAction.NO_FIX,
        use.edge.symbol_name,
        use.edge.alias,
        reason=reason,
    )


def _fix(use: _Use, context: _Context) -> LeakFix:
    """Prove the fix of one statement or say why there is none.

    The fix is ``from <facade> import <name>`` and needs, in this order: a name (not a
    module), a public ancestor package that re-exports it, no guard around that re-export,
    no second binding of the name there, and a facade that does not import the consumer
    when it loads.

    Args:
        use: The use.
        context: Shared context.

    Returns:
        The fix, or the entry with its reason.
    """
    symbol = use.edge.symbol_name
    if symbol is None:
        return _no_fix(use, context, LeakNoFix.MODULE_IMPORT)
    if not use.facades:
        offered = context.offers.get((use.edge.target, symbol), ())
        reason = LeakNoFix.NOT_ANCESTOR if offered else LeakNoFix.NO_PUBLIC_PATH
        return _no_fix(use, context, reason)
    facade = use.facades[0]
    if passes_guard(facade, symbol, context.index, context.guarded):
        return _no_fix(use, context, LeakNoFix.GUARDED)
    if (facade, symbol) in context.rebound:
        return _no_fix(use, context, LeakNoFix.REBOUND)
    if use.importer.name in _reachable(facade, context):
        return _no_fix(use, context, LeakNoFix.CYCLE)
    return LeakFix(
        _location(use, context),
        use.importer.name,
        LeakAction.FACADE_IMPORT,
        symbol,
        use.edge.alias,
        facade,
    )


def _module(name: str, uses: list[_Use], context: _Context) -> LeakModule:
    """Summarize every use of one written module.

    Args:
        name: The written module.
        uses: Its uses.
        context: Shared context.

    Returns:
        The leak.
    """
    verdict = classify_module(name, context.api)
    if verdict is ApiVerdict.PUBLIC:
        kind, reason = LeakKind.BYPASS, LeakReason.FACADE
    else:
        kind = LeakKind.INTERNAL
        declared = verdict is ApiVerdict.DECLARED_INTERNAL
        reason = LeakReason.DECLARED if declared else LeakReason.CONVENTION
    fixes = tuple(
        sorted((_fix(use, context) for use in uses), key=lambda f: (f.location, f.symbol or ""))
    )
    roots = Counter(_root_of(use.importer.name) for use in uses)
    return LeakModule(
        name,
        kind,
        reason,
        len({use.importer.name for use in uses}),
        tuple(sorted(roots.items(), key=lambda item: (-item[1], item[0]))),
        fixes,
        sum(1 for fix in fixes if fix.action is LeakAction.FACADE_IMPORT),
    )


def summarize_leaks(
    result: ParseResult, import_graph: nx.DiGraph, api: ApiContract
) -> list[LeakModule]:
    """Find the modules outside code reaches into, with the fix of each statement.

    Args:
        result: Parsed project with re-exports resolved and ``api_leaks`` on.
        import_graph: Dependencies that exist when modules are imported (``MODULE`` edges).
        api: The contract declared in ``[api]``.

    Returns:
        One entry per written module: internal ones first, then by consumers, then by name.
    """
    context = _context(result, import_graph, api)
    grouped: dict[str, list[_Use]] = defaultdict(list)
    seen: set[tuple[str, int | None, str, str | None]] = set()
    for module in result.modules:
        for edge in module.imports:
            use = _use(module, edge, context)
            key = (module.name, edge.line_number, edge.written or edge.target, edge.symbol_name)
            if use is not None and key not in seen:
                seen.add(key)
                grouped[use.written].append(use)
    leaks = [_module(name, uses, context) for name, uses in grouped.items()]
    return sorted(
        leaks, key=lambda leak: (leak.kind is not LeakKind.INTERNAL, -leak.consumers, leak.name)
    )


def _fix_summary(fix: LeakFix) -> str:
    """Render one fix for the AI and the evidence: location and action.

    Args:
        fix: The fix.

    Returns:
        ``path:line from facade import x`` or ``path:line no_fix (reason)``.
    """
    if fix.action is LeakAction.NO_FIX:
        return f"{fix.location} {fix.action} ({fix.reason})"
    name = fix.symbol if fix.alias is None else f"{fix.symbol} as {fix.alias}"
    return f"{fix.location} from {fix.facade} import {name}"


def find_api_leaks(leaks: Iterable[LeakModule]) -> list[Finding]:
    """Apply rule 13: one finding per module outside code reaches into.

    Args:
        leaks: From ``summarize_leaks``.

    Returns:
        The findings, in the same order.
    """
    findings = []
    for leak in leaks:
        evidence: Evidence = {
            "kind": leak.kind.value,
            "reason": leak.reason.value,
            "consumers": leak.consumers,
            "roots": ROOT_SEPARATOR.join(
                f"{root}{ROOT_COUNT_SEPARATOR}{count}" for root, count in leak.roots
            ),
            "statements": len(leak.fixes),
            "fixed": leak.fixed,
            "no_fix": len(leak.fixes) - leak.fixed,
            "fixes": FIX_SEPARATOR.join(_fix_summary(fix) for fix in leak.fixes[:MAX_FIXES_SHOWN]),
            "fixes_total": len(leak.fixes),
        }
        findings.append(Finding(FindingKind.API_LEAK, (leak.name,), evidence))
    return findings
