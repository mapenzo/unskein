"""Rule 10: imports of project modules that do not exist and would break when they run."""

from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass, field

from unskein.graph.distributions import ImportUse, import_use, relative_path
from unskein.graph.findings import Evidence, Finding, FindingKind
from unskein.parsers.models import ParseResult

MAX_IMPORTERS_SHOWN = 5
LIST_SEPARATOR = ", "
FIX_IMPORT_FROM = "import_from"
FIX_RESTORE_OR_REMOVE = "restore_or_remove"
BREAKING_USES = (ImportUse.REQUIRED, ImportUse.LAZY)


@dataclass(slots=True)
class _Missing:
    """What the project imports from one module that does not exist.

    Attributes:
        counts: Statements per use.
        first: First breaking statement (``path:line``), if any.
        importers: Modules that import it.
        closest: Closest ancestor that exists.
        symbols: Names imported from it.
    """

    counts: defaultdict[ImportUse, int] = field(default_factory=lambda: defaultdict(int))
    first: str | None = None
    importers: set[str] = field(default_factory=set)
    closest: str = ""
    symbols: set[str] = field(default_factory=set)


def _definitions(result: ParseResult) -> dict[str, list[str]]:
    """Index which modules bind each name at module level, by name.

    A module does not define a name it imports from a module that does not exist:
    that binding would fail too.

    Args:
        result: Parsed project.

    Returns:
        The modules, sorted, that bind each name.
    """
    defined: defaultdict[str, list[str]] = defaultdict(list)
    for module in sorted(result.modules, key=lambda m: m.name):
        broken = {
            edge.symbol_name
            for edge in module.imports
            if edge.requested is not None and edge.symbol_name is not None
        }
        for name in module.bound_names:
            if name not in broken:
                defined[name].append(module.name)
    return defined


def _collect(result: ParseResult, scripts: Collection[str]) -> dict[str, _Missing]:
    """Tally every internal import of a module that does not exist.

    Args:
        result: Parsed project, re-exports resolved.
        scripts: Unpackaged modules nothing imports.

    Returns:
        What is imported from each missing module, by its name; ``first`` is set only
        when some statement breaks (packaged source, not a script, required or lazy).
    """
    missing: defaultdict[str, _Missing] = defaultdict(_Missing)
    sources = sorted(
        (relative_path(module.file_path, result.project_root), module) for module in result.modules
    )
    for relative, module in sources:
        can_break = module.is_packaged and module.name not in scripts
        for edge in sorted(module.imports, key=lambda e: e.line_number or 0):
            use = None if edge.is_external or edge.requested is None else import_use(edge)
            if use is None:
                continue
            entry = missing[edge.requested]
            entry.counts[use] += 1
            entry.importers.add(module.name)
            entry.closest = edge.target
            if edge.symbol_name is not None:
                entry.symbols.add(edge.symbol_name)
            if can_break and use in BREAKING_USES and entry.first is None:
                line = f":{edge.line_number}" if edge.line_number is not None else ""
                entry.first = f"{relative}{line}"
    return missing


def find_missing_modules(result: ParseResult, scripts: Collection[str]) -> list[Finding]:
    """Apply rule 10: packaged code imports a module that does not exist, unguarded.

    Imports under ``TYPE_CHECKING``, guarded ones and those of unpackaged code stay
    warnings only. The fix comes from evidence: a module that defines the imported name,
    or the statement that none does.

    Args:
        result: Parsed project, re-exports resolved.
        scripts: Unpackaged modules nothing imports.

    Returns:
        One finding per missing module with a breaking import, sorted by its name.
    """
    definitions = _definitions(result)
    findings = []
    for name, entry in sorted(_collect(result, scripts).items()):
        if entry.first is None:
            continue
        evidence: Evidence = {
            "required": entry.counts[ImportUse.REQUIRED],
            "lazy": entry.counts[ImportUse.LAZY],
            "guarded": entry.counts[ImportUse.GUARDED],
            "first": entry.first,
            "importers": LIST_SEPARATOR.join(sorted(entry.importers)[:MAX_IMPORTERS_SHOWN]),
            "closest": entry.closest,
            "symbols": LIST_SEPARATOR.join(sorted(entry.symbols)),
            "fix": FIX_RESTORE_OR_REMOVE,
        }
        defined = sorted({module for symbol in entry.symbols for module in definitions[symbol]})
        if defined:
            evidence |= {
                "fix": FIX_IMPORT_FROM,
                "defined_in": defined[0],
                "also_defined": len(defined) - 1,
            }
        findings.append(Finding(FindingKind.MISSING_MODULE, (name,), evidence))
    return findings
