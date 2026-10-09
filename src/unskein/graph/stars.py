"""Rule 12: star imports, the names each one really needs and the explicit import to write."""

from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from unskein.graph.findings import Evidence, Finding, FindingKind
from unskein.parsers.indirection import Star, star_cycles, star_imports, wildcard_names
from unskein.parsers.layout import relative_path
from unskein.parsers.models import ModuleInfo, ParseResult

# Caps of the fixes sent to the AI; the report shows every statement and name.
MAX_FIXES_SHOWN = 5
MAX_NAMES_SHOWN = 20
LIST_SEPARATOR = ", "
FIX_SEPARATOR = "; "
LINE_SEPARATOR = ":"
NAME_SEPARATOR = "."
KIND_MODULE = "module"
KIND_SELF = "self"
# Needer of the names a module keeps because it is used by itself: any may be read.
ANY_READER = ""


class WildcardAction(StrEnum):
    """What to do with one star import.

    Attributes:
        REMOVE: It needs no name; remove it.
        EXPLICIT: Replace it with an explicit import of the names it needs.
        REMOVE_SELF: A package imports itself without ``__all__``; it does nothing.
    """

    REMOVE = "remove"
    EXPLICIT = "explicit"
    REMOVE_SELF = "remove_self"


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
    """

    location: str
    importer: str
    action: WildcardAction
    names: tuple[str, ...] = ()
    kept: tuple[str, ...] = ()
    kept_for: tuple[tuple[str, str], ...] = ()
    defined_elsewhere: tuple[tuple[str, str], ...] = ()
    external: tuple[str, ...] = ()


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
    """

    by_name: Mapping[str, ModuleInfo]
    providers: Mapping[str, dict[str, list[Star]]]
    demand: Mapping[str, set[str]]
    needer: Mapping[tuple[str, str], str]
    root: Path | None


def _providers(
    statements: list[Star],
    brings: Mapping[str, frozenset[str] | None],
    shadowed: Collection[str] = (),
) -> dict[str, list[Star]]:
    """Return, for each name, every star statement of a module that brings it.

    Every one is kept, not only the last: stars in alternative branches (``try`` and
    ``except``, ``if`` and ``else``) may each be the one that runs, and an explicit import
    of a name the module also binds keeps the same meaning whatever the order.

    Args:
        statements: The module's star statements, in code order.
        brings: Names each star-imported module brings.
        shadowed: Names the module rebinds for good after its stars: none provides them.

    Returns:
        The statements that bring each name.
    """
    providers: defaultdict[str, list[Star]] = defaultdict(list)
    for statement in statements:
        for name in brings.get(statement[1]) or ():
            if name not in shadowed:
                providers[name].append(statement)
    return providers


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
    for module in result.modules:
        demand[module.name].update(module.stars.reads)
        for edge in module.imports:
            if edge.is_external:
                continue
            names = (edge.symbol_name,) if edge.symbol_name is not None else edge.attribute_reads
            for name in names:
                demand[edge.target].add(name)
                needer.setdefault((edge.target, name), module.name)
            if edge.attribute_escapes:
                opaque.add(edge.target)
        for _, base in stars.get(module.name, []):
            if brings.get(base) is None:
                opaque.add(base)
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
    by_name = {module.name: module for module in result.modules}
    providers = {}
    for name, statements in stars.items():
        module = by_name.get(name)
        shadowed = module.stars.shadowed if module is not None else ()
        providers[name] = _providers(statements, brings, shadowed)
    demand, needer = _initial_demand(result, stars, brings)
    changed = True
    while changed:
        changed = False
        for importer, by_name in providers.items():
            for name in list(demand[importer]):
                for _, base in by_name.get(name, ()):
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
    """Build the fix of one star statement.

    Args:
        module: Module that holds it.
        statement: (line, star-imported module).
        context: Project-wide data.

    Returns:
        Remove it when it needs nothing; otherwise the explicit import, with notes.
    """
    line, base = statement
    location = _location(module, line, context.root)
    providers = context.providers[module.name]
    names = tuple(
        sorted(n for n in context.demand[module.name] if statement in providers.get(n, ()))
    )
    if not names:
        return WildcardFix(location, module.name, WildcardAction.REMOVE)
    reads = set(module.stars.reads)
    kept = tuple(name for name in names if name not in reads)
    kept_for = tuple(
        sorted((context.needer.get((module.name, name), module.name), name) for name in kept)
    )
    elsewhere, external = _origins(context.by_name[base], names, context.providers.get(base, {}))
    return WildcardFix(
        location, module.name, WildcardAction.EXPLICIT, names, kept, kept_for, elsewhere, external
    )


def summarize_wildcards(result: ParseResult, scripts: Collection[str]) -> list[WildcardModule]:
    """Compute the fix of every star import of packaged code, grouped by imported module.

    Demand comes from every analyzed module, scripts and analyzed tests included, so a fix
    never drops a name another analyzed module needs; only packaged code that is no script
    gets fixes. When in doubt a name is kept: an extra name only lengthens a fix. Stars
    whose names cannot be known, or in a cycle of star imports, get no fix (they warn).

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
    context = _Context(by_name, providers, demand, needer, result.project_root)
    cycles = star_cycles(stars)
    grouped: defaultdict[tuple[str, bool], list[WildcardFix]] = defaultdict(list)
    for module in result.modules:
        if not module.is_packaged or module.name in scripts:
            continue
        for line, base in module.stars.statements:
            if base == module.name:
                if not module.declares_all and not module.has_dynamic_all:
                    location = _location(module, line, result.project_root)
                    grouped[base, True].append(
                        WildcardFix(location, module.name, WildcardAction.REMOVE_SELF)
                    )
            elif brings.get(base) is not None and (module.name, base) not in cycles:
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
            "reexported": wildcard.reexported,
            "fixes": FIX_SEPARATOR.join(
                _fix_summary(fix, wildcard.name) for fix in wildcard.fixes[:MAX_FIXES_SHOWN]
            ),
            "fixes_total": len(wildcard.fixes),
        }
        findings.append(Finding(FindingKind.WILDCARD_IMPORT, (wildcard.name,), evidence))
    return findings
