"""Hold the language-neutral data produced by parsing: modules, imports and re-exports."""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class WarningCode(StrEnum):
    """Kinds of non-fatal problems found while parsing and resolving a project.

    Attributes:
        STAR_IMPORT: ``from x import *``; the exported names cannot be known.
        RELATIVE_BEYOND_TOP: A relative import climbs above the top-level package.
        UNRESOLVED_IMPORT: An internal import names a module that does not exist.
        FILE_TOO_LARGE: A file exceeds ``max_file_size_bytes`` and was not read.
        PARSE_ERROR: A file could not be read or parsed and was skipped.
        REEXPORT_CYCLE: Re-exports of a symbol form a cycle.
        REEXPORT_DEPTH_EXCEEDED: A re-export chain is longer than the resolution limit.
    """

    STAR_IMPORT = "star_import"
    RELATIVE_BEYOND_TOP = "relative_beyond_top"
    UNRESOLVED_IMPORT = "unresolved_import"
    FILE_TOO_LARGE = "file_too_large"
    PARSE_ERROR = "parse_error"
    REEXPORT_CYCLE = "reexport_cycle"
    REEXPORT_DEPTH_EXCEEDED = "reexport_depth_exceeded"


@dataclass(frozen=True, slots=True)
class ParseWarning:
    """A non-fatal problem, kept structured so the report can translate and group it.

    Frozen so identical warnings deduplicate in sets and dict keys.

    Attributes:
        code: Kind of problem.
        path: Source file it refers to, or None for project-level problems
            such as re-export cycles.
        line: Line in that file, when known.
        detail: Language-neutral data for the message (module names, sizes,
            the underlying exception text); never a translated sentence.
    """

    code: WarningCode
    path: Path | None
    line: int | None
    detail: str


@dataclass(slots=True)
class ImportEdge:
    """One import from a project module to another module.

    Attributes:
        source: Dotted name of the importing module.
        target: Dotted name of the imported module (for internal imports, a
            module that exists in the project).
        is_external: Whether the target lies outside the project, decided by
            comparing its first segment with the project's top-level packages.
        symbol_name: Imported symbol, or None when the whole module is imported.
        line_number: Line of the import statement in the source file.
    """

    source: str
    target: str
    is_external: bool
    symbol_name: str | None = None
    line_number: int | None = None


@dataclass(slots=True)
class ModuleInfo:
    """A parsed project module and the imports it makes.

    Attributes:
        name: Dotted module name, e.g. "app.services.user".
        file_path: Source file the module was parsed from.
        imports: Imports found in the module.
    """

    name: str
    file_path: Path
    imports: list[ImportEdge] = field(default_factory=list)


@dataclass(slots=True)
class ReExport:
    """A symbol that a package facade exposes on behalf of another module.

    Attributes:
        exporting_module: Module that re-exports the symbol (the facade).
        original_module: Module the facade imports the symbol from.
        symbol_name: Name under which the facade exposes the symbol.
    """

    exporting_module: str
    original_module: str
    symbol_name: str


@dataclass
class ParseResult:
    """Everything a language adapter extracted from a project.

    Attributes:
        modules: Successfully parsed modules.
        language: Name of the language the modules are written in.
        re_exports: Re-exports detected in package facades.
        warnings: Problems that skipped a file or an import without stopping
            the analysis.
    """

    modules: list[ModuleInfo]
    language: str
    re_exports: list[ReExport] = field(default_factory=list)
    warnings: list[ParseWarning] = field(default_factory=list)
