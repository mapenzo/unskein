"""Rule 12: star imports, the names each one really needs and the explicit import to write."""

from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from unskein.graph.findings import Evidence, Finding, FindingKind
from unskein.parsers.layout import relative_path
from unskein.parsers.models import STAR_EXPORT, ModuleInfo, ParseResult

MAX_FIXES_SHOWN = 5
MAX_NAMES_SHOWN = 20
LIST_SEPARATOR = ", "
FIX_SEPARATOR = "; "
LINE_SEPARATOR = ":"
NAME_SEPARATOR = "."
KIND_MODULE = "module"
KIND_SELF = "self"

# A star statement: (line, star-imported module).
Star = tuple[int, str]


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
        kept_for: First module that needs a kept name.
        defined_elsewhere: (origin module, name) of names the star-imported module only
            passes on, sorted.
        external: Names that reach it from a third-party import, sorted.
    """

    location: str
    importer: str
    action: WildcardAction
    names: tuple[str, ...] = ()
    kept: tuple[str, ...] = ()
    kept_for: str | None = None
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


def _stars_of(result: ParseResult) -> dict[str, list[Star]]:
    """Return the star imports of every module, facades included, in code order.

    Args:
        result: Parsed project.

    Returns:
        Each module's star statements; facade re-exports have no line (0).
    """
    stars: defaultdict[str, list[Star]] = defaultdict(list)
    for re_export in result.re_exports:
        if re_export.symbol_name == STAR_EXPORT:
            stars[re_export.exporting_module].append((0, re_export.original_module))
    for module in result.modules:
        stars[module.name].extend(
            (line, base) for line, base in module.wildcards if base != module.name
        )
    return stars


def _star_names(
    base: str, by_name: Mapping[str, ModuleInfo], stars: Mapping[str, list[Star]]
) -> frozenset[str] | None:
    """Return the names ``from base import *`` brings, following nested star imports.

    Args:
        base: Star-imported module.
        by_name: Parsed modules by name.
        stars: Star imports of every module.

    Returns:
        The names; None when some module on the way was not parsed or computes ``__all__``.
    """
    names: set[str] = set()
    seen = {base}
    pending = [base]
    while pending:
        module = by_name.get(pending.pop())
        if module is None or module.has_dynamic_all:
            return None
        names.update(module.public_names)
        if module.declares_all:
            continue
        for _, nested in stars.get(module.name, []):
            if nested not in seen:
                seen.add(nested)
                pending.append(nested)
    return frozenset(names)


def _owners(
    module: ModuleInfo | None, statements: list[Star], brings: Mapping[str, frozenset[str] | None]
) -> dict[str, Star]:
    """Return which star statement of a module provides each name: the last one wins.

    Args:
        module: The importing module, if parsed.
        statements: Its star statements, in code order.
        brings: Names each star-imported module brings.

    Returns:
        The owning statement of each name the module does not bind itself.
    """
    own = set(module.bound_names) if module is not None else set()
    owners: dict[str, Star] = {}
    for statement in statements:
        for name in brings.get(statement[1]) or ():
            if name not in own:
                owners[name] = statement
    return owners


def _demand(
    result: ParseResult, stars: Mapping[str, list[Star]], owners: Mapping[str, dict[str, Star]]
) -> tuple[dict[str, set[str]], dict[tuple[str, str], str]]:
    """Find the names every module must provide, and who needs the ones it never reads.

    A module needs what it reads, what other modules import from it explicitly, and what
    the modules that star-import it need through it (a fixpoint over the star graph).

    Args:
        result: Parsed project, re-exports resolved.
        stars: Star imports of every module.
        owners: Owning statement of each name, per module.

    Returns:
        The needed names per module, and the first module needing each (module, name)
        through someone else.
    """
    demand: defaultdict[str, set[str]] = defaultdict(set)
    needer: dict[tuple[str, str], str] = {}
    for module in result.modules:
        demand[module.name].update(module.star_reads)
        for edge in module.imports:
            if not edge.is_external and edge.symbol_name is not None:
                demand[edge.target].add(edge.symbol_name)
                needer.setdefault((edge.target, edge.symbol_name), module.name)
    changed = True
    while changed:
        changed = False
        for importer in stars:
            for name in list(demand[importer]):
                owner = owners[importer].get(name)
                if owner is None or name in demand[owner[1]]:
                    continue
                demand[owner[1]].add(name)
                needer.setdefault((owner[1], name), needer.get((importer, name), importer))
                changed = True
    return demand, needer


def _origins(
    base: ModuleInfo, names: Iterable[str], owners: Mapping[str, Star]
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    """Tell which needed names the star-imported module only passes on, and from where.

    Args:
        base: The star-imported module.
        names: Names a statement needs from it.
        owners: Owning star statement of each name inside ``base``.

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
        elif name in owners:
            internal.add((owners[name][1], name))
    return tuple(sorted(internal)), tuple(sorted(external))


@dataclass(frozen=True, slots=True)
class _Context:
    """Project-wide data the fixes need.

    Attributes:
        by_name: Parsed modules by name.
        owners: Owning star statement of each name, per module.
        demand: Names each module must provide.
        needer: First module needing each (module, name) through someone else.
        root: Project root, for relative paths.
    """

    by_name: Mapping[str, ModuleInfo]
    owners: Mapping[str, dict[str, Star]]
    demand: Mapping[str, set[str]]
    needer: Mapping[tuple[str, str], str]
    root: Path | None


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
    owners = context.owners[module.name]
    names = tuple(sorted(n for n in context.demand[module.name] if owners.get(n) == statement))
    if not names:
        return WildcardFix(location, module.name, WildcardAction.REMOVE)
    reads = set(module.star_reads)
    kept = tuple(name for name in names if name not in reads)
    kept_for = context.needer.get((module.name, kept[0])) if kept else None
    elsewhere, external = _origins(context.by_name[base], names, context.owners[base])
    return WildcardFix(
        location, module.name, WildcardAction.EXPLICIT, names, kept, kept_for, elsewhere, external
    )


def summarize_wildcards(result: ParseResult, scripts: Collection[str]) -> list[WildcardModule]:
    """Compute the fix of every star import of packaged code, grouped by imported module.

    Demand comes from every module, tests and scripts included, so a fix never drops a
    name a test imports through the module; only packaged code that is no script gets
    fixes.

    Args:
        result: Parsed project, re-exports resolved.
        scripts: Unpackaged modules nothing imports.

    Returns:
        One entry per star-imported module (and per package importing itself), most
        importers first, then by name.
    """
    by_name = {module.name: module for module in result.modules}
    stars = _stars_of(result)
    bases = {base for statements in stars.values() for _, base in statements}
    brings = {base: _star_names(base, by_name, stars) for base in bases}
    owners: defaultdict[str, dict[str, Star]] = defaultdict(dict)
    for name, statements in stars.items():
        owners[name] = _owners(by_name.get(name), statements, brings)
    demand, needer = _demand(result, stars, owners)
    context = _Context(by_name, owners, demand, needer, result.project_root)
    grouped: defaultdict[tuple[str, bool], list[WildcardFix]] = defaultdict(list)
    for module in result.modules:
        if not module.is_packaged or module.name in scripts:
            continue
        for line, base in module.wildcards:
            if base == module.name:
                if not module.declares_all and not module.has_dynamic_all:
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
    return sorted(summaries, key=lambda w: (-w.importers, w.name))


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
