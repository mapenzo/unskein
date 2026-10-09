"""Hold the language-neutral data produced by parsing: modules, imports and re-exports."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Self


class WarningCode(StrEnum):
    """Kinds of non-fatal problems found while parsing and resolving a project.

    Attributes:
        STAR_IMPORT: ``from x import *`` outside a package facade (or of a module outside
            the project); the names it brings in are not followed.
        RELATIVE_BEYOND_TOP: A relative import climbs above the top-level package.
        UNRESOLVED_IMPORT: An internal import names a module that does not exist.
        FILE_TOO_LARGE: A file exceeds ``max_file_size_bytes`` and was not read.
        PARSE_ERROR: A file could not be read or parsed and was skipped.
        PARSE_TIMEOUT: Parsing a file exceeded ``per_file_timeout_seconds``; it was skipped.
        REEXPORT_CYCLE: Re-exports of a symbol form a cycle.
        REEXPORT_DEPTH_EXCEEDED: A re-export chain is longer than the resolution limit.
        MANIFEST_UNREADABLE: A ``pyproject.toml`` or ``setup.cfg`` could not be read or
            parsed; its distribution is detected with the heuristic.
        DECLARED_PACKAGE_MISSING: A manifest declares a package that does not exist on disk.
        MODULE_NAME_COLLISION: Two files would take the same module name; the one in the
            shallower distribution is named by its path.
        INVALID_REQUIREMENT: A declared dependency (or an included dependency group) has
            no usable name; it is ignored.
    """

    STAR_IMPORT = "star_import"
    RELATIVE_BEYOND_TOP = "relative_beyond_top"
    UNRESOLVED_IMPORT = "unresolved_import"
    FILE_TOO_LARGE = "file_too_large"
    PARSE_ERROR = "parse_error"
    PARSE_TIMEOUT = "parse_timeout"
    REEXPORT_CYCLE = "reexport_cycle"
    REEXPORT_DEPTH_EXCEEDED = "reexport_depth_exceeded"
    MANIFEST_UNREADABLE = "manifest_unreadable"
    DECLARED_PACKAGE_MISSING = "declared_package_missing"
    MODULE_NAME_COLLISION = "module_name_collision"
    INVALID_REQUIREMENT = "invalid_requirement"


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


class ImportKind(StrEnum):
    """Where an import statement sits, which decides whether it exists at import time.

    Attributes:
        MODULE: At module level (also in class bodies, ``try``/``except`` and ``if``
            blocks): it runs when the module is imported.
        LAZY: Inside a function or method body: it runs only when that function is called.
        TYPE_CHECKING: Under ``if TYPE_CHECKING:``: it never runs, type checkers only.
    """

    MODULE = "module"
    LAZY = "lazy"
    TYPE_CHECKING = "type_checking"

    def stronger(self, other: Self) -> Self:
        """Return the kind that runs more often.

        Args:
            other: Kind to compare with.

        Returns:
            ``self`` or ``other``, whichever is closer to ``MODULE``.
        """
        return self if _KIND_STRENGTH[self] >= _KIND_STRENGTH[other] else other

    def weaker(self, other: Self) -> Self:
        """Return the kind that runs less often.

        Args:
            other: Kind to compare with.

        Returns:
            ``self`` or ``other``, whichever is closer to ``TYPE_CHECKING``.
        """
        return self if _KIND_STRENGTH[self] <= _KIND_STRENGTH[other] else other


_KIND_STRENGTH = {ImportKind.MODULE: 2, ImportKind.LAZY: 1, ImportKind.TYPE_CHECKING: 0}


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
        kind: Where the statement sits; see ``ImportKind``.
        accessed: Dotted attribute chains the module reads through the name this
            import binds, sorted (``algorithms.shortest_path`` for ``nx.algorithms.shortest_path``);
            only filled for imports of a package whose use was analyzed.
        escapes: Whether that name is also used by itself (passed, assigned, rebound),
            so its attribute accesses do not tell everything the module depends on.
        is_guarded: Whether the statement sits in the body of a ``try`` that catches import
            errors, or of ``with contextlib.suppress(...)`` for them; such an import is
            optional by contract.
    """

    source: str
    target: str
    is_external: bool
    symbol_name: str | None = None
    line_number: int | None = None
    kind: ImportKind = ImportKind.MODULE
    accessed: tuple[str, ...] = ()
    escapes: bool = False
    is_guarded: bool = False


@dataclass(slots=True)
class ModuleInfo:
    """A parsed project module and the imports it makes.

    Attributes:
        name: Dotted module name, e.g. "app.services.user".
        file_path: Source file the module was parsed from.
        imports: Imports found in the module.
        public_names: Names the module exposes to ``from module import *``, sorted.
        declares_all: Whether those names come from a literal ``__all__``.
        bound_names: Every name the module binds at module level, sorted.
        is_packaged: Whether a distribution ships the module; unpackaged modules that
            nothing imports are scripts.
    """

    name: str
    file_path: Path
    imports: list[ImportEdge] = field(default_factory=list)
    public_names: tuple[str, ...] = ()
    declares_all: bool = False
    bound_names: tuple[str, ...] = ()
    is_packaged: bool = True


# Symbol name of a ReExport that stands for a whole ``from x import *`` in a facade.
STAR_EXPORT = "*"


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


@dataclass(slots=True)
class FileParseResult:
    """What parsing a single file produced.

    Attributes:
        module: The parsed module, or None when the file was skipped.
        re_exports: Re-exports found in the file (only package facades have any).
        warnings: Problems found while parsing the file.
    """

    module: ModuleInfo | None
    re_exports: list[ReExport] = field(default_factory=list)
    warnings: list[ParseWarning] = field(default_factory=list)


ParseTask = tuple[Path, str]


@dataclass(frozen=True, slots=True)
class ParsePlan:
    """How to parse a set of files: the units of work and what they all share.

    Splitting the two lets a process pool send ``shared`` once per worker
    instead of once per file.

    Attributes:
        tasks: Files to parse with their module names, in the order results
            must be combined.
        shared: Read-only data every task needs (for Python, the project index);
            must be picklable.
        warnings: Problems found while naming the files (manifests, collisions).
        entry_points: Modules the project's distributions declare as scripts.
    """

    tasks: list[ParseTask]
    shared: Any
    warnings: list[ParseWarning] = field(default_factory=list)
    entry_points: tuple[str, ...] = ()


@dataclass
class ParseResult:
    """Everything a language adapter extracted from a project.

    Attributes:
        modules: Successfully parsed modules.
        language: Name of the language the modules are written in.
        re_exports: Re-exports detected in package facades.
        warnings: Problems that skipped a file or an import without stopping
            the analysis.
        entry_points: Modules the project's distributions declare as scripts.
    """

    modules: list[ModuleInfo]
    language: str
    re_exports: list[ReExport] = field(default_factory=list)
    warnings: list[ParseWarning] = field(default_factory=list)
    entry_points: tuple[str, ...] = ()

    @classmethod
    def from_file_results(
        cls,
        language: str,
        file_results: Iterable[FileParseResult],
        *,
        plan: ParsePlan | None = None,
    ) -> Self:
        """Combine per-file results, in the order given, into one project result.

        Args:
            language: Name of the language the modules are written in.
            file_results: One result per parsed file.
            plan: The plan the files were parsed from; its warnings come first and its
                entry points are kept.

        Returns:
            The combined result; skipped files contribute only their warnings.
        """
        result = cls(modules=[], language=language)
        if plan is not None:
            result.warnings.extend(plan.warnings)
            result.entry_points = plan.entry_points
        for file_result in file_results:
            if file_result.module is not None:
                result.modules.append(file_result.module)
            result.re_exports.extend(file_result.re_exports)
            result.warnings.extend(file_result.warnings)
        return result
