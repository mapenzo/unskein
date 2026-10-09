"""Rule 10: imports of project modules that do not exist and would break when they run."""

from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass, field

from unskein.graph.distributions import ImportUse, import_use
from unskein.graph.findings import Evidence, Finding, FindingKind
from unskein.parsers.layout import relative_path
from unskein.parsers.models import ParseResult

MAX_IMPORTERS_SHOWN = 5
LIST_SEPARATOR = ", "
# Pairs a symbol with its module or count in the evidence: "helper:app.util".
PAIR_SEPARATOR = ":"
FIX_IMPORT_FROM = "import_from"
FIX_RESTORE_OR_REMOVE = "restore_or_remove"
BREAKING_USES = (ImportUse.REQUIRED, ImportUse.LAZY)
NAME_SEPARATOR = "."


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


def _definitions(result: ParseResult, scripts: Collection[str]) -> dict[str, list[str]]:
    """Index which packaged modules define each name themselves, by name.

    A name bound by an import (``from json import JSONDecoder as Tokenizer``) is not a
    definition: suggesting that module would point at an alias, or at another library.
    Scripts and unpackaged modules are left out: importing from them would break too.

    Args:
        result: Parsed project.
        scripts: Unpackaged modules nothing imports.

    Returns:
        The modules, sorted, that define each name with ``def``, ``class`` or an assignment.
    """
    defined: defaultdict[str, list[str]] = defaultdict(list)
    for module in sorted(result.modules, key=lambda m: m.name):
        if module.is_packaged and module.name not in scripts:
            for name in module.defined_names:
                defined[name].append(module.name)
    return defined


def _closest(name: str, known: frozenset[str]) -> str:
    """Return the closest existing ancestor of a name, as the import wrote it.

    Computed from the requested name, not from the edge target, which re-export
    resolution may have moved to another module.

    Args:
        name: Dotted name the import asked for.
        known: Project modules and namespace packages.

    Returns:
        The longest prefix of the name that exists; empty when none does.
    """
    parts = name.split(NAME_SEPARATOR)
    for end in range(len(parts) - 1, 0, -1):
        candidate = NAME_SEPARATOR.join(parts[:end])
        if candidate in known:
            return candidate
    return ""


def _inside_native(closest: str, result: ParseResult) -> bool:
    """Tell whether a missing name sits under compiled code or a stub.

    Compiled code can register submodules unskein cannot see, so a name under it is not
    known to be missing.

    Args:
        closest: Closest existing ancestor of the missing name.
        result: Parsed project.

    Returns:
        True when that ancestor is a compiled extension or a stub-only module.
    """
    found = result.virtual.get(closest)
    return found is not None and found.kind.is_native


def _collect(result: ParseResult, scripts: Collection[str]) -> dict[str, _Missing]:
    """Tally the imports of modules that do not exist, made by packaged code.

    Tests, scripts and other unpackaged code are left out of the counts: the finding is
    about what breaks once the package is installed.

    Args:
        result: Parsed project, re-exports resolved.
        scripts: Unpackaged modules nothing imports.

    Returns:
        What is imported from each missing module, by its name; ``first`` is set only
        when some statement breaks (required or lazy).
    """
    known = frozenset(module.name for module in result.modules) | frozenset(result.virtual)
    missing: defaultdict[str, _Missing] = defaultdict(_Missing)
    # Only packaged modules with a broken import: relative paths are slow on many files.
    sources = sorted(
        (relative_path(module.file_path, result.project_root), module)
        for module in result.modules
        if module.is_packaged
        and module.name not in scripts
        and any(edge.requested is not None for edge in module.imports)
    )
    for relative, module in sources:
        for edge in sorted(module.imports, key=lambda e: e.line_number or 0):
            use = None if edge.is_external or edge.requested is None else import_use(edge)
            if use is None:
                continue
            entry = missing[edge.requested]
            entry.counts[use] += 1
            entry.importers.add(module.name)
            entry.closest = _closest(edge.requested, known)
            if edge.symbol_name is not None:
                entry.symbols.add(edge.symbol_name)
            if use in BREAKING_USES and entry.first is None:
                line = f":{edge.line_number}" if edge.line_number is not None else ""
                entry.first = f"{relative}{line}"
    return missing


def _fix_evidence(entry: _Missing, definitions: dict[str, list[str]]) -> Evidence:
    """Return the fix of a missing module, from what the project defines, symbol by symbol.

    Args:
        entry: What is imported from the missing module.
        definitions: Packaged modules that define each name.

    Returns:
        ``import_from`` with the defining module of each symbol that has one (and how many
        more define it) plus the symbols no module defines; ``restore_or_remove`` when no
        symbol is defined anywhere else.
    """
    found: dict[str, list[str]] = {}
    for symbol in sorted(entry.symbols):
        modules = [m for m in definitions.get(symbol, []) if m not in entry.importers]
        if modules:
            found[symbol] = modules
    if not found:
        return {"fix": FIX_RESTORE_OR_REMOVE}
    return {
        "fix": FIX_IMPORT_FROM,
        "defined_in": LIST_SEPARATOR.join(f"{s}{PAIR_SEPARATOR}{m[0]}" for s, m in found.items()),
        "also_defined": LIST_SEPARATOR.join(
            f"{s}{PAIR_SEPARATOR}{len(m) - 1}" for s, m in found.items()
        ),
        "undefined": LIST_SEPARATOR.join(s for s in sorted(entry.symbols) if s not in found),
    }


def find_missing_modules(result: ParseResult, scripts: Collection[str]) -> list[Finding]:
    """Apply rule 10: packaged code imports a module that does not exist, unguarded.

    Imports under ``TYPE_CHECKING``, guarded ones and those of unpackaged code stay
    warnings only. A module that exists as a stub or a compiled extension is in the
    project index, so its imports are never missing, and a name under one is not known
    to be missing either (compiled code can register submodules). The fix comes from evidence: the
    module that defines each imported name, or the statement that none does.

    Args:
        result: Parsed project, re-exports resolved.
        scripts: Unpackaged modules nothing imports.

    Returns:
        One finding per missing module with a breaking import, sorted by its name.
    """
    definitions = _definitions(result, scripts)
    findings = []
    for name, entry in sorted(_collect(result, scripts).items()):
        if entry.first is None or _inside_native(entry.closest, result):
            continue
        evidence: Evidence = {
            "required": entry.counts[ImportUse.REQUIRED],
            "lazy": entry.counts[ImportUse.LAZY],
            "guarded": entry.counts[ImportUse.GUARDED],
            "first": entry.first,
            "importers": LIST_SEPARATOR.join(sorted(entry.importers)[:MAX_IMPORTERS_SHOWN]),
            "closest": entry.closest,
            "symbols": LIST_SEPARATOR.join(sorted(entry.symbols)),
        }
        evidence |= _fix_evidence(entry, definitions)
        findings.append(Finding(FindingKind.MISSING_MODULE, (name,), evidence))
    return findings
