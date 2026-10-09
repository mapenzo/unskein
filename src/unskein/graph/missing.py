"""Rule 10: imports of project modules that do not exist and would break when they run."""

from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

from unskein.graph.distributions import ImportUse, import_use, relative_path
from unskein.graph.findings import Evidence, Finding, FindingKind
from unskein.parsers.models import ParseResult

MAX_IMPORTERS_SHOWN = 5
LIST_SEPARATOR = ", "
FIX_IMPORT_FROM = "import_from"
FIX_RESTORE_OR_REMOVE = "restore_or_remove"
BREAKING_USES = (ImportUse.REQUIRED, ImportUse.LAZY)
NAME_SEPARATOR = "."
PACKAGE_INIT_FILE = "__init__.py"
# A module with no .py source can still exist: a type stub or a compiled extension.
STUB_SUFFIX = ".pyi"
STUB_INIT = "__init__.pyi"
COMPILED_SUFFIXES = (".so", ".pyd")


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
    """Index which modules define each name themselves, by name.

    A name bound by an import (``from json import JSONDecoder as Tokenizer``) is not a
    definition: suggesting that module would point at an alias, or at another library.

    Args:
        result: Parsed project.

    Returns:
        The modules, sorted, that define each name with ``def``, ``class`` or an assignment.
    """
    defined: defaultdict[str, list[str]] = defaultdict(list)
    for module in sorted(result.modules, key=lambda m: m.name):
        for name in module.defined_names:
            defined[name].append(module.name)
    return defined


def _package_directory(name: str, result: ParseResult) -> Path | None:
    """Return the directory of a package, also of a namespace package with no file.

    Args:
        name: Dotted name of an existing package.
        result: Parsed project.

    Returns:
        Its directory, or None when it is a plain module (it cannot hold submodules).
    """
    depth = len(name.split(NAME_SEPARATOR))
    for module in result.modules:
        if module.name == name:
            is_facade = module.file_path.name == PACKAGE_INIT_FILE
            return module.file_path.parent if is_facade else None
        if module.name.startswith(f"{name}{NAME_SEPARATOR}"):
            below = len(module.name.split(NAME_SEPARATOR)) - depth
            if module.file_path.name == PACKAGE_INIT_FILE:
                below += 1
            return module.file_path.parents[below - 1]
    return None


def _exists_without_source(name: str, closest: str, result: ParseResult) -> bool:
    """Tell whether a module that has no ``.py`` file exists as a stub or a compiled binary.

    Args:
        name: Dotted name the import asked for.
        closest: Its closest existing ancestor.
        result: Parsed project.

    Returns:
        True when a ``.pyi`` stub, an ``__init__.pyi`` or a compiled extension (``.so``,
        ``.pyd``) is there.
    """
    directory = _package_directory(closest, result)
    if directory is None:
        return False
    rest = name.split(NAME_SEPARATOR)[len(closest.split(NAME_SEPARATOR)) :]
    candidate = directory.joinpath(*rest)
    if candidate.with_suffix(STUB_SUFFIX).is_file() or (candidate / STUB_INIT).is_file():
        return True
    if not candidate.parent.is_dir():
        return False
    stem = f"{candidate.name}."
    return any(
        path.name.startswith(stem) and path.suffix in COMPILED_SUFFIXES
        for path in candidate.parent.iterdir()
    )


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
    # Only modules with a broken import: relative paths are slow on thousands of files.
    sources = sorted(
        (relative_path(module.file_path, result.project_root), module)
        for module in result.modules
        if any(edge.requested is not None for edge in module.imports)
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
    warnings only, and so do modules that exist without a ``.py`` file (a stub or a
    compiled extension). The fix comes from evidence: a module that defines the imported name,
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
        if entry.first is None or _exists_without_source(name, entry.closest, result):
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
