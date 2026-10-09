"""Rule 12: star imports, the names each one really needs and the explicit import to write."""

from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import networkx as nx

from unskein.graph.findings import Evidence, Finding, FindingKind
from unskein.parsers.indirection import (
    Star,
    star_imports,
    wildcard_conditional,
    wildcard_names,
)
from unskein.parsers.layout import relative_path
from unskein.parsers.models import ImportKind, ModuleInfo, ParseResult
from unskein.parsers.usage import collect_attribute_reads

# Caps of the fixes sent to the AI; the report shows every statement and name.
MAX_FIXES_SHOWN = 5
MAX_NAMES_SHOWN = 20
LIST_SEPARATOR = ", "
FIX_SEPARATOR = "; "
LINE_SEPARATOR = ":"
NAME_SEPARATOR = "."
KIND_MODULE = "module"
KIND_SELF = "self"
PACKAGE_INIT_FILE = "__init__.py"
# Needer of the names a module keeps because it is used by itself: any may be read.
ANY_READER = ""


class WildcardAction(StrEnum):
    """What to do with one star import.

    Attributes:
        REMOVE: It needs no name; remove it.
        EXPLICIT: Replace it with an explicit import of the names it needs.
        REMOVE_SELF: A package imports itself without ``__all__``; it does nothing.
        NO_FIX: No fix can be proven safe; ``WildcardFix.reason`` says why.
    """

    REMOVE = "remove"
    EXPLICIT = "explicit"
    REMOVE_SELF = "remove_self"
    NO_FIX = "no_fix"


class WildcardReason(StrEnum):
    """Why a star import gets no fix.

    Attributes:
        CONDITIONAL: A needed name may be unbound when the star runs (bound only inside a
            block, under ``TYPE_CHECKING``, only annotated or deleted).
        CYCLE: The importer and the imported module import each other: what the star
            brings depends on import order.
        SUBMODULE: The module reads a submodule of the imported package that another module
            may have loaded, so the star may or may not bring it.
    """

    CONDITIONAL = "conditional"
    CYCLE = "cycle"
    SUBMODULE = "submodule"


@dataclass(frozen=True, slots=True)
class WildcardFix:
    """The fix of one star import statement.

    Attributes:
        location: ``path:line`` of the statement.
        importer: Module that holds it.
        action: What to do with it.
        names: Names the explicit import must list, sorted.
        kept: Those of them the importer never reads: other modules need them through it.
        kept_for: (module that needs it, name) for each kept name, sorted; the module is
            ``ANY_READER`` when the importer is used by itself, so any name may be read.
        defined_elsewhere: (origin module, name) of names the star-imported module only
            passes on, sorted.
        external: Names that reach it from a third-party import, sorted.
        reason: Why there is no fix, for ``NO_FIX``.
        reason_names: The names behind that reason, sorted.
    """

    location: str
    importer: str
    action: WildcardAction
    names: tuple[str, ...] = ()
    kept: tuple[str, ...] = ()
    kept_for: tuple[tuple[str, str], ...] = ()
    defined_elsewhere: tuple[tuple[str, str], ...] = ()
    external: tuple[str, ...] = ()
    reason: WildcardReason | None = None
    reason_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WildcardModule:
    """Every star import of one module (or the self star imports of one package).

    Attributes:
        name: The star-imported module, or the package that imports itself.
        is_self: Whether these are ``from . import *`` of a package into itself.
        names: How many names a star import of it brings.
        fixes: One fix per statement, sorted by location.
    """

    name: str
    is_self: bool
    names: int
    fixes: tuple[WildcardFix, ...]

    @property
    def importers(self) -> int:
        """Return how many modules hold these statements."""
        return len({fix.importer for fix in self.fixes})

    @property
    def used_min(self) -> int:
        """Return the fewest names a statement needs."""
        return min(len(fix.names) for fix in self.fixes)

    @property
    def used_max(self) -> int:
        """Return the most names a statement needs."""
        return max(len(fix.names) for fix in self.fixes)

    @property
    def unused(self) -> int:
        """Return how many statements need no name."""
        return sum(1 for fix in self.fixes if fix.action is WildcardAction.REMOVE)

    @property
    def no_fix(self) -> int:
        """Return how many statements get no fix."""
        return sum(1 for fix in self.fixes if fix.action is WildcardAction.NO_FIX)

    @property
    def reexported(self) -> int:
        """Return how many names are kept only because other modules need them."""
        return sum(len(fix.kept) for fix in self.fixes)


@dataclass(frozen=True, slots=True)
class _Context:
    """Project-wide data the fixes need.

    Attributes:
        by_name: Parsed modules by name.
        providers: Star statements that bring each name, per module.
        demand: Names each module must provide.
        needer: First module needing each (module, name) through someone else.
        root: Project root, for relative paths.
        cycles: Group of mutually importing modules each module belongs to, if any.
        conditional: Names each star-imported module may leave unbound.
        unloaded: Submodules of each star-imported package its star may or may not bring.
    """

    by_name: Mapping[str, ModuleInfo]
    providers: Mapping[str, dict[str, list[Star]]]
    demand: Mapping[str, set[str]]
    needer: Mapping[tuple[str, str], str]
    root: Path | None
    cycles: Mapping[str, int]
    conditional: Mapping[str, frozenset[str]]
    unloaded: Mapping[str, frozenset[str]]


def _providers(
    statements: list[Star], brings: Mapping[str, frozenset[str] | None]
) -> dict[str, list[Star]]:
    """Return, for each name, every star statement of a module that brings it.

    Every one is kept, not only the last: stars in alternative branches (``try`` and
    ``except``, ``if`` and ``else``) may each be the one that runs, and an explicit import
    of a name the module also binds keeps the same meaning whatever the order.

    Args:
        statements: The module's star statements, in code order.
        brings: Names each star-imported module brings.

    Returns:
        The statements that bring each name.
    """
    providers: defaultdict[str, list[Star]] = defaultdict(list)
    for statement in statements:
        for name in brings.get(statement[1]) or ():
            providers[name].append(statement)
    return providers


def _is_public_facade(module: ModuleInfo, stars: Mapping[str, list[Star]]) -> bool:
    """Tell whether a package facade re-exports star imports as its public API.

    Code outside the project may read any name such a facade exposes, so every name its
    stars bring must stay.

    Args:
        module: A parsed module.
        stars: Star imports of every module.

    Returns:
        True for an ``__init__.py`` without ``__all__`` that has star imports.
    """
    return (
        module.file_path.name == PACKAGE_INIT_FILE
        and not module.declares_all
        and bool(stars.get(module.name))
    )


def _initial_demand(
    result: ParseResult,
    stars: Mapping[str, list[Star]],
    brings: Mapping[str, frozenset[str] | None],
) -> tuple[defaultdict[str, set[str]], dict[tuple[str, str], str]]:
    """Collect what each module needs before following star imports.

    A module needs what it reads, the names any module imports from it explicitly or reads
    as attributes of it, and everything its stars bring when its use cannot be analyzed:
    it is used by itself, or a star of it brings names nobody can know.

    Args:
        result: Parsed project, re-exports resolved.
        stars: Star imports of every module.
        brings: Names each star-imported module brings.

    Returns:
        The needed names per module, and the first module needing each (module, name).
    """
    demand: defaultdict[str, set[str]] = defaultdict(set)
    needer: dict[tuple[str, str], str] = {}
    opaque: set[str] = set()
    by_name = {module.name: module for module in result.modules}
    for module in result.modules:
        demand[module.name].update(module.stars.reads)
        opaque.update(name for name in module.stars.dynamic_imports if name in by_name)
        star_lines = {line for line, _ in module.stars.statements}
        whole = set()
        for edge in module.imports:
            if edge.is_external:
                continue
            if edge.symbol_name is not None:
                demand[edge.target].add(edge.symbol_name)
                needer.setdefault((edge.target, edge.symbol_name), module.name)
            elif edge.target in stars and edge.line_number not in star_lines:
                target = by_name.get(edge.target)
                if target is not None and target.file_path.name == PACKAGE_INIT_FILE:
                    # Package imports already carry their attribute reads.
                    for chain in edge.accessed:
                        demand[edge.target].add(chain.split(NAME_SEPARATOR)[0])
                        needer.setdefault(
                            (edge.target, chain.split(NAME_SEPARATOR)[0]), module.name
                        )
                    if edge.escapes:
                        opaque.add(edge.target)
                else:
                    whole.add(edge.target)
        if whole:
            for target, (reads, escapes) in collect_attribute_reads(module, whole, None).items():
                for name in reads:
                    demand[target].add(name)
                    needer.setdefault((target, name), module.name)
                if escapes:
                    opaque.add(target)
        for _, base in stars.get(module.name, []):
            if brings.get(base) is None:
                opaque.add(base)
        if _is_public_facade(module, stars):
            opaque.add(module.name)
    for name in opaque:
        for _, base in stars.get(name, []):
            for brought in brings.get(base) or ():
                demand[name].add(brought)
                needer.setdefault((name, brought), ANY_READER)
    return demand, needer


def _demand(
    result: ParseResult,
    stars: Mapping[str, list[Star]],
    brings: Mapping[str, frozenset[str] | None],
) -> tuple[dict[str, set[str]], dict[tuple[str, str], str], dict[str, dict[str, list[Star]]]]:
    """Find the names every module must provide, following star imports to a fixpoint.

    Args:
        result: Parsed project, re-exports resolved.
        stars: Star imports of every module.
        brings: Names each star-imported module brings.

    Returns:
        The needed names per module, the first module needing each (module, name) through
        someone else, and the star statements that bring each name, per module.
    """
    providers = {name: _providers(statements, brings) for name, statements in stars.items()}
    demand, needer = _initial_demand(result, stars, brings)
    changed = True
    while changed:
        changed = False
        for importer, by_statement in providers.items():
            for name in list(demand[importer]):
                for _, base in by_statement.get(name, ()):
                    if name not in demand[base]:
                        demand[base].add(name)
                        needer.setdefault((base, name), needer.get((importer, name), importer))
                        changed = True
    return demand, needer, providers


def _origins(
    base: ModuleInfo, names: Iterable[str], providers: Mapping[str, list[Star]]
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    """Tell which needed names the star-imported module only passes on, and from where.

    Only for the notes of a fix; an aliased import gives no note.

    Args:
        base: The star-imported module.
        names: Names a statement needs from it.
        providers: Star statements that bring each name inside ``base``.

    Returns:
        (origin module, name) of internal ones, and the names that come from a
        third-party import.
    """
    internal: set[tuple[str, str]] = set()
    external: set[str] = set()
    defined = set(base.defined_names)
    for name in names:
        if name in defined:
            continue
        edge = next(
            (
                e
                for e in base.imports
                if e.symbol_name == name
                or (e.symbol_name is None and e.target.split(NAME_SEPARATOR)[0] == name)
            ),
            None,
        )
        if edge is not None and edge.is_external:
            external.add(name)
        elif edge is not None:
            internal.add((edge.target, name))
        elif name in providers:
            internal.update((statement[1], name) for statement in providers[name])
    return tuple(sorted(internal)), tuple(sorted(external))


def _location(module: ModuleInfo, line: int, root: Path | None) -> str:
    """Return ``path:line`` of a statement, relative to the project root.

    Args:
        module: Module that holds it.
        line: Its line.
        root: Project root.

    Returns:
        The location.
    """
    return f"{relative_path(module.file_path, root)}{LINE_SEPARATOR}{line}"


def _fix(module: ModuleInfo, statement: Star, context: _Context) -> WildcardFix:
    """Build the fix of one star statement, or say why none is safe.

    Args:
        module: Module that holds it.
        statement: (line, star-imported module).
        context: Project-wide data.

    Returns:
        Remove it when it needs nothing; otherwise the explicit import, with notes; or no
        fix with its reason.
    """
    line, base = statement
    location = _location(module, line, context.root)
    providers = context.providers[module.name]
    names = tuple(
        sorted(n for n in context.demand[module.name] if statement in providers.get(n, ()))
    )
    cycle = context.cycles.get(module.name)
    if cycle is not None and cycle == context.cycles.get(base):
        return WildcardFix(
            location, module.name, WildcardAction.NO_FIX, names, reason=WildcardReason.CYCLE
        )
    loaded_elsewhere = tuple(sorted(set(module.stars.reads) & context.unloaded.get(base, set())))
    if loaded_elsewhere:
        return WildcardFix(
            location,
            module.name,
            WildcardAction.NO_FIX,
            names,
            reason=WildcardReason.SUBMODULE,
            reason_names=loaded_elsewhere,
        )
    if not names:
        return WildcardFix(location, module.name, WildcardAction.REMOVE)
    unbound = tuple(name for name in names if name in context.conditional.get(base, ()))
    if unbound:
        return WildcardFix(
            location,
            module.name,
            WildcardAction.NO_FIX,
            names,
            reason=WildcardReason.CONDITIONAL,
            reason_names=unbound,
        )
    reads = set(module.stars.reads)
    kept = tuple(name for name in names if name not in reads)
    kept_for = tuple(
        sorted((context.needer.get((module.name, name), module.name), name) for name in kept)
    )
    elsewhere, external = _origins(context.by_name[base], names, context.providers.get(base, {}))
    return WildcardFix(
        location, module.name, WildcardAction.EXPLICIT, names, kept, kept_for, elsewhere, external
    )


def _import_cycles(result: ParseResult) -> dict[str, int]:
    """Return the group of mutually importing modules (at import time) of each module.

    Args:
        result: Parsed project, re-exports resolved.

    Returns:
        A group number per module that sits in a cycle of module-level imports.
    """
    graph = nx.DiGraph(
        (module.name, edge.target)
        for module in result.modules
        for edge in module.imports
        if not edge.is_external and edge.kind is ImportKind.MODULE
    )
    groups: dict[str, int] = {}
    for number, component in enumerate(nx.strongly_connected_components(graph)):
        if len(component) > 1:
            groups.update(dict.fromkeys(component, number))
    return groups


def _unloaded_submodules(
    bases: Iterable[str],
    by_name: Mapping[str, ModuleInfo],
    brings: Mapping[str, frozenset[str] | None],
    names: Collection[str],
) -> dict[str, frozenset[str]]:
    """Return the submodules of each star-imported package its star may or may not bring.

    A star of a package without ``__all__`` brings a submodule only if it was imported
    before, here or by another module: the source cannot tell.

    Args:
        bases: Star-imported modules.
        by_name: Parsed modules by name.
        brings: Names each star-imported module brings.
        names: Every module and namespace package of the project.

    Returns:
        The uncertain submodule names of each package.
    """
    unloaded: dict[str, frozenset[str]] = {}
    for base in bases:
        module = by_name.get(base)
        if module is None or module.declares_all or module.file_path.name != PACKAGE_INIT_FILE:
            continue
        start = f"{base}{NAME_SEPARATOR}"
        children = {n[len(start) :].split(NAME_SEPARATOR)[0] for n in names if n.startswith(start)}
        unloaded[base] = frozenset(children - (brings.get(base) or frozenset()))
    return unloaded


def summarize_wildcards(result: ParseResult, scripts: Collection[str]) -> list[WildcardModule]:
    """Compute the fix of every star import of packaged code, grouped by imported module.

    A fix is given only when it can be proven safe: the names it lists are bound for sure
    by the imported module, the two modules do not import each other, and no module reads
    a submodule the star may or may not bring. Otherwise the statement gets no fix and its
    reason. Demand comes from every analyzed module, scripts and analyzed tests included.
    Stars whose names cannot be known get no entry (they warn).

    Args:
        result: Parsed project, re-exports resolved.
        scripts: Unpackaged modules nothing imports.

    Returns:
        One entry per star-imported module (and per package importing itself), most
        importers first, then by name.
    """
    by_name = {module.name: module for module in result.modules}
    stars = star_imports(result.modules, result.re_exports)
    bases = {base for statements in stars.values() for _, base in statements}
    brings = {base: wildcard_names(base, by_name, stars) for base in bases}
    demand, needer, providers = _demand(result, stars, brings)
    every_name = set(by_name) | set(result.virtual)
    context = _Context(
        by_name,
        providers,
        demand,
        needer,
        result.project_root,
        _import_cycles(result),
        {base: wildcard_conditional(base, by_name, stars) for base in bases},
        _unloaded_submodules(bases, by_name, brings, every_name),
    )
    grouped: defaultdict[tuple[str, bool], list[WildcardFix]] = defaultdict(list)
    for module in result.modules:
        if not module.is_packaged or module.name in scripts:
            continue
        for line, base in module.stars.statements:
            if base == module.name:
                if not module.declares_all and not module.surface.dynamic_all:
                    location = _location(module, line, result.project_root)
                    grouped[base, True].append(
                        WildcardFix(location, module.name, WildcardAction.REMOVE_SELF)
                    )
            elif brings.get(base) is not None:
                grouped[base, False].append(_fix(module, (line, base), context))
    summaries = [
        WildcardModule(
            name,
            is_self,
            0 if is_self else len(brings[name] or ()),
            tuple(sorted(fixes, key=lambda fix: fix.location)),
        )
        for (name, is_self), fixes in grouped.items()
    ]
    return sorted(summaries, key=lambda w: (-w.importers, w.name, w.is_self))


def _fix_summary(fix: WildcardFix, module: str) -> str:
    """Render one fix for the AI: location and action, names capped.

    Args:
        fix: The fix.
        module: The star-imported module.

    Returns:
        ``path:line remove`` or ``path:line from module import a, b``.
    """
    if fix.action is WildcardAction.NO_FIX:
        return f"{fix.location} {fix.action} ({fix.reason})"
    if fix.action is not WildcardAction.EXPLICIT:
        return f"{fix.location} {fix.action}"
    names = list(fix.names[:MAX_NAMES_SHOWN])
    if len(fix.names) > MAX_NAMES_SHOWN:
        names.append(f"+{len(fix.names) - MAX_NAMES_SHOWN}")
    return f"{fix.location} from {module} import {LIST_SEPARATOR.join(names)}"


def find_wildcard_imports(wildcards: Iterable[WildcardModule]) -> list[Finding]:
    """Apply rule 12: one finding per star-imported module, with its summary.

    Args:
        wildcards: From ``summarize_wildcards``.

    Returns:
        The findings, in the same order.
    """
    findings = []
    for wildcard in wildcards:
        evidence: Evidence = {
            "kind": KIND_SELF if wildcard.is_self else KIND_MODULE,
            "importers": wildcard.importers,
            "statements": len(wildcard.fixes),
            "names": wildcard.names,
            "used_min": wildcard.used_min,
            "used_max": wildcard.used_max,
            "unused_statements": wildcard.unused,
            "no_fix_statements": wildcard.no_fix,
            "reexported": wildcard.reexported,
            "fixes": FIX_SEPARATOR.join(
                _fix_summary(fix, wildcard.name) for fix in wildcard.fixes[:MAX_FIXES_SHOWN]
            ),
            "fixes_total": len(wildcard.fixes),
        }
        findings.append(Finding(FindingKind.WILDCARD_IMPORT, (wildcard.name,), evidence))
    return findings
