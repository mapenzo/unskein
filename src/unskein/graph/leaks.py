"""Rule 13: code outside a package imports what the package keeps internal."""

import ast
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import networkx as nx

from unskein.config import ApiContract
from unskein.graph.findings import Evidence, Finding, FindingKind
from unskein.parsers.discovery import parse_source
from unskein.parsers.exports import name_binding
from unskein.parsers.indirection import (
    ReExportIndex,
    build_reexport_index,
    guarded_reexports,
    passes_guard,
    resolve_target,
    star_exports,
)
from unskein.parsers.layout import relative_path
from unskein.parsers.models import ImportEdge, ModuleInfo, ParseResult

MAX_FIXES_SHOWN = 5
FIX_SEPARATOR = "; "
ROOT_SEPARATOR = "; "
ROOT_COUNT_SEPARATOR = " "
ALIAS_KEYWORD = " as "
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
        REBOUND: The facade (or a module on the way to the definition) binds the name more
            than once, deletes it, or writes its namespace in a way that cannot be read.
        CONDITIONAL: The facade imports the name inside an ``if``, a function or a class body.
        RENAMED: The facade exports a different object under that name.
        MODULE_IMPORT: The statement imports a module, not a name.
    """

    NO_PUBLIC_PATH = "no_public_path"
    NOT_ANCESTOR = "not_ancestor"
    CYCLE = "cycle"
    GUARDED = "guarded"
    REBOUND = "rebound"
    CONDITIONAL = "conditional"
    RENAMED = "renamed"
    MODULE_IMPORT = "module_import"


# Reasons that still leave the facade offering the same object: it is a bypass all the same.
BYPASS_REASONS = frozenset({LeakNoFix.GUARDED, LeakNoFix.CYCLE})


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


@dataclass(slots=True)
class _Context:
    """What proving a fix needs: facts computed once per project, and two caches.

    The caches (``trees`` and ``reach``) are filled on demand while fixes are proven.

    Attributes:
        modules: Parsed modules by name.
        names: Every project module name, virtual ones included.
        root: Project root, for relative paths.
        api: The declared contract.
        index: Re-export index.
        guarded: Guarded re-exports.
        offers: Packages that offer each (defining module, name), nearest ancestor first.
        star_count: How many star imports of each (module, name) bring the name in.
        import_graph: Dependencies that exist when modules are imported.
        trees: Source of each module read again, by name; None when it cannot be read.
        reach: What each facade imports when it loads.
    """

    modules: Mapping[str, ModuleInfo]
    names: frozenset[str]
    root: Path | None
    api: ApiContract
    index: ReExportIndex
    guarded: frozenset[tuple[str, str]]
    offers: Mapping[tuple[str, str], tuple[str, ...]]
    star_count: Counter[tuple[str, str]]
    import_graph: nx.DiGraph
    trees: dict[str, ast.Module | None] = field(default_factory=dict)
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
    star_count: Counter[tuple[str, str]] = Counter()
    for (module, _), names in stars.items():
        star_count.update((module, name) for name in names)
    return _Context(
        modules={module.name: module for module in result.modules},
        names=frozenset(module.name for module in result.modules) | frozenset(result.virtual),
        root=result.project_root,
        api=api,
        index=index,
        guarded=guarded_reexports(result.re_exports, stars),
        offers=_offers(index),
        star_count=star_count,
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


def _facades(
    edge: ImportEdge, written: str, context: _Context, *, importer: str
) -> tuple[str, ...]:
    """List the public ancestor packages of a module that offer the imported name.

    The importer's own package never counts: its import of the name is the leak itself.

    Args:
        edge: The import edge.
        written: Module the statement named.
        context: Shared context.
        importer: Module that holds the statement.

    Returns:
        The packages, nearest first; empty for a whole-module import.
    """
    if edge.symbol_name is None:
        return ()
    exporters = context.offers.get((edge.target, edge.symbol_name), ())
    return tuple(
        exporter
        for exporter in exporters
        if exporter != importer
        and written.startswith(exporter + SEGMENT_SEPARATOR)
        and _is_public(exporter, context.api)
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
    facades = _facades(edge, written, context, importer=importer.name)
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


def _tree(module: str, context: _Context) -> ast.Module | None:
    """Read a project module again, once.

    Args:
        module: Dotted module name.
        context: Shared context; caches the tree.

    Returns:
        Its syntax tree, or None when it is not a parsed module or cannot be read any more.
    """
    if module not in context.trees:
        info = context.modules.get(module)
        context.trees[module] = parse_source(info.file_path, None) if info else None
    return context.trees[module]


def _is_plain_from_import(use: _Use, context: _Context) -> bool:
    """Tell whether the statement is a ``from <written> import <name>`` the fix can rewrite.

    Whole-module imports read through an attribute (``import lib.core as c`` and ``c.Name``)
    give edges with a symbol too; replacing their line would drop the binding they create.

    Args:
        use: The use.
        context: Shared context.

    Returns:
        True when the line holds that statement, binding the name the edge records.
    """
    tree = _tree(use.importer.name, context)
    if tree is None:
        return False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.lineno == use.edge.line_number
            and node.level == 0
            and node.module == use.written
        ):
            for alias in node.names:
                bound = None if alias.asname in (None, alias.name) else alias.asname
                if alias.name == use.edge.symbol_name and bound == use.edge.alias:
                    return True
    return False


def _hop_status(module: str, symbol: str, context: _Context) -> LeakNoFix | None:
    """Prove that a module binds a re-exported name exactly once, unconditionally.

    Args:
        module: A package or module the name passes through.
        symbol: The re-exported name.
        context: Shared context.

    Returns:
        None when it is a single plain ``from x import name`` directly in the module body
        (or the only star import that brings the name), else the reason it is not.
    """
    tree = _tree(module, context)
    if tree is None:
        return LeakNoFix.REBOUND
    binding = name_binding(tree, symbol)
    stars = context.star_count[(module, symbol)]
    total = binding.sites + stars
    if binding.uncertain or total > 1:
        return LeakNoFix.REBOUND
    if total == 0:
        return LeakNoFix.CONDITIONAL
    if stars == 1 or binding.plain_import:
        return None
    if binding.renamed:
        return LeakNoFix.RENAMED
    return LeakNoFix.CONDITIONAL if binding.in_block else LeakNoFix.REBOUND


def _path(start: str, symbol: str, target: str, context: _Context) -> list[str]:
    """List the modules a name passes through from ``start`` down to its definition.

    Args:
        start: Module the name is imported from.
        symbol: The name.
        target: Module that defines it.
        context: Shared context.

    Returns:
        ``start`` and every re-exporting module after it, up to but not including ``target``.
    """
    modules: list[str] = []
    module = start
    while module != target and module not in modules and (module, symbol) in context.index:
        modules.append(module)
        module = context.index[(module, symbol)]
    return modules


def _chain_status(use: _Use, facade: str, context: _Context) -> LeakNoFix | None:
    """Check every module between the consumer's import and the facade's import.

    The name the consumer gets today comes through the written module's own chain and the
    name the fix would give through the facade's; both must lead to the one definition.

    Args:
        use: The use.
        facade: The package the fix would import from.
        context: Shared context.

    Returns:
        The first reason a module on either path is not a plain single binding, or None.
    """
    symbol = str(use.edge.symbol_name)
    paths = [_path(facade, symbol, use.edge.target, context)]
    if use.written != use.edge.target:
        paths.append(_path(use.written, symbol, use.edge.target, context))
    for module in (module for path in paths for module in path):
        status = _hop_status(module, symbol, context)
        if status is not None:
            return status
    return None


def _fix(use: _Use, context: _Context) -> LeakFix:
    """Prove the fix of one statement or say why there is none.

    The fix is ``from <facade> import <name>`` and needs, in this order: a statement that
    is a plain ``from … import name``, a public ancestor package that re-exports it, no
    guard around that re-export, every module the name passes through binding it exactly
    once and unconditionally without renaming it, no submodule of the facade with that
    name, and a facade that does not import the consumer when it loads.

    Args:
        use: The use.
        context: Shared context.

    Returns:
        The fix, or the entry with its reason.
    """
    symbol = use.edge.symbol_name
    if symbol is None or not _is_plain_from_import(use, context):
        return _no_fix(use, context, LeakNoFix.MODULE_IMPORT)
    if not use.facades:
        offered = [
            exporter
            for exporter in context.offers.get((use.edge.target, symbol), ())
            if exporter != use.importer.name
        ]
        reason = LeakNoFix.NOT_ANCESTOR if offered else LeakNoFix.NO_PUBLIC_PATH
        return _no_fix(use, context, reason)
    facade = use.facades[0]
    if passes_guard(facade, symbol, context.index, context.guarded):
        return _no_fix(use, context, LeakNoFix.GUARDED)
    status = _chain_status(use, facade, context)
    if status is None and f"{facade}{SEGMENT_SEPARATOR}{symbol}" in context.names:
        status = LeakNoFix.REBOUND
    if status is not None:
        return _no_fix(use, context, status)
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


def _module(name: str, fixes: list[LeakFix], context: _Context) -> LeakModule:
    """Summarize every statement that imports one written module.

    Args:
        name: The written module.
        fixes: The fix, or reason for none, of each statement.
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
    ordered = tuple(sorted(fixes, key=lambda fix: (fix.location, fix.symbol or "")))
    roots = Counter(_root_of(fix.importer) for fix in ordered)
    return LeakModule(
        name,
        kind,
        reason,
        len({fix.importer for fix in ordered}),
        tuple(sorted(roots.items(), key=lambda item: (-item[1], item[0]))),
        ordered,
        sum(1 for fix in ordered if fix.action is LeakAction.FACADE_IMPORT),
    )


def _is_bypass(fix: LeakFix) -> bool:
    """Tell whether a statement really goes around a facade that offers the same object.

    A facade that only imports the name under ``TYPE_CHECKING``, in a function, under another
    name, or that rebinds it does not offer that object, so importing around it is no bypass.

    Args:
        fix: The fix, or the reason for none, of a statement into a public module.

    Returns:
        True when the fix exists, or is withheld only for a guard or an import cycle.
    """
    return fix.action is LeakAction.FACADE_IMPORT or fix.reason in BYPASS_REASONS


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
    grouped: dict[str, list[LeakFix]] = defaultdict(list)
    seen: set[tuple[str, int | None, str, str | None]] = set()
    for module in result.modules:
        for edge in module.imports:
            use = _use(module, edge, context)
            key = (module.name, edge.line_number, edge.written or edge.target, edge.symbol_name)
            if use is None or key in seen:
                continue
            seen.add(key)
            fix = _fix(use, context)
            is_public = classify_module(use.written, context.api) is ApiVerdict.PUBLIC
            if not is_public or _is_bypass(fix):
                grouped[use.written].append(fix)
    leaks = [_module(name, fixes, context) for name, fixes in grouped.items()]
    return sorted(
        leaks, key=lambda leak: (leak.kind is not LeakKind.INTERNAL, -leak.consumers, leak.name)
    )


def import_name(fix: LeakFix) -> str:
    """Render the name a fix imports, with the alias the statement binds.

    Args:
        fix: A fix with a symbol.

    Returns:
        ``symbol`` or ``symbol as alias``.
    """
    return f"{fix.symbol}{ALIAS_KEYWORD}{fix.alias}" if fix.alias else str(fix.symbol)


def _fix_summary(fix: LeakFix) -> str:
    """Render one fix for the AI and the evidence: location and action.

    Args:
        fix: The fix.

    Returns:
        ``path:line from facade import x`` or ``path:line no_fix (reason)``.
    """
    if fix.action is LeakAction.NO_FIX:
        return f"{fix.location} {fix.action} ({fix.reason})"
    return f"{fix.location} from {fix.facade} import {import_name(fix)}"


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
