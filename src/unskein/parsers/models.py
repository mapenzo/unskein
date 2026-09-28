"""Hold the language-neutral data produced by parsing: modules, imports and re-exports."""

from dataclasses import dataclass, field
from pathlib import Path


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
    warnings: list[str] = field(default_factory=list)
