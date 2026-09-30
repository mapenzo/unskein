"""Parse Python source files with `ast` into modules, imports and re-exports."""

import ast
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pathspec

from unskein.config import AnalysisConfig
from unskein.parsers.base import LanguageAdapter
from unskein.parsers.discovery import detect_encoding, walk_files
from unskein.parsers.models import (
    FileParseResult,
    ImportEdge,
    ModuleInfo,
    ParsePlan,
    ParseTask,
    ParseWarning,
    ReExport,
    WarningCode,
)

# Import statements only occur in statement lists; ``handlers`` holds ExceptHandler
# nodes and ``cases`` holds match_case nodes, each with its own ``body``. The order
# is the one in which a compound statement's blocks appear in the source.
STATEMENT_LIST_FIELDS = ("body", "handlers", "cases", "orelse", "finalbody")


def iter_statements(tree: ast.Module) -> Iterator[ast.AST]:
    """Yield every statement of a module, nested ones included, in code order.

    Skips expressions on purpose: ``ast.walk`` visits millions of expression
    nodes that can never contain an import.

    Args:
        tree: Parsed module.

    Yields:
        Each statement, exception handler and match case, depth-first.
    """
    stack = list(reversed(tree.body))
    while stack:
        node = stack.pop()
        yield node
        for field_name in reversed(STATEMENT_LIST_FIELDS):
            if children := getattr(node, field_name, None):
                stack.extend(reversed(children))


@dataclass(frozen=True, slots=True)
class ProjectIndex:
    """Names of every module in the project, used to classify and resolve imports.

    Attributes:
        modules: Dotted names of all project modules.
        top_level: First segments of those names (the project's top-level packages).
    """

    modules: frozenset[str]
    top_level: frozenset[str]

    @classmethod
    def from_names(cls, names: set[str]) -> "ProjectIndex":
        """Build the index from the project's module names.

        Args:
            names: Dotted names of all project modules.

        Returns:
            The index over those names.
        """
        return cls(frozenset(names), frozenset(n.split(".")[0] for n in names))

    def is_external(self, name: str) -> bool:
        """Return whether a module name lies outside the project.

        Args:
            name: Dotted module name taken from an import.

        Returns:
            True when its first segment is not one of the project's top-level packages.
        """
        return name.split(".")[0] not in self.top_level

    def closest_module(self, name: str) -> str | None:
        """Return the longest prefix of a name that is a project module.

        Args:
            name: Dotted name taken from an import.

        Returns:
            The closest existing module, or None when no prefix exists in the project.
        """
        parts = name.split(".")
        for end in range(len(parts), 0, -1):
            candidate = ".".join(parts[:end])
            if candidate in self.modules:
                return candidate
        return None


def _absolute(path: Path) -> Path:
    """Return an absolute path without resolving symlinks.

    Args:
        path: Path to make absolute.

    Returns:
        The absolute, normalized path.
    """
    # abspath, not resolve(): a followed symlink must keep its in-project link path.
    return Path(os.path.abspath(path))


def resolve_source_roots(root: Path, configured: list[str] | None) -> list[Path]:
    """Return the source roots module names are computed from, most specific first.

    Without configuration, a `src/` directory that is not itself a package is
    detected as a source root. The project root is always the last fallback.

    Args:
        root: Project directory.
        configured: Source roots relative to root, or None to auto-detect.

    Returns:
        Absolute source roots, deepest first.
    """
    if configured is None:
        src = root / "src"
        configured = ["src"] if src.is_dir() and not (src / "__init__.py").exists() else []
    roots = [_absolute(root / r) for r in configured]
    absolute_root = _absolute(root)
    if absolute_root not in roots:
        roots.append(absolute_root)
    return sorted(roots, key=lambda p: len(p.parts), reverse=True)


def module_name(file_path: Path, source_roots: list[Path]) -> str:
    """Return the dotted module name of a file relative to its source root.

    `__init__.py` collapses to its package name; a package at the source root
    itself takes the root directory's name.

    Args:
        file_path: Python source file.
        source_roots: Roots from `resolve_source_roots`, deepest first.

    Returns:
        The dotted module name, e.g. "app.services.user".

    Raises:
        ValueError: If the file is outside every source root.
    """
    absolute = _absolute(file_path)
    for source_root in source_roots:
        if absolute.is_relative_to(source_root):
            parts = list(absolute.relative_to(source_root).with_suffix("").parts)
            if parts and parts[-1] == "__init__":
                parts.pop()
            return ".".join(parts) or source_root.name
    raise ValueError(f"{file_path} is outside every source root")


class _ImportCollector:
    """Collect the imports, re-exports and warnings of one parsed module.

    Args:
        file_path: Source file being parsed (used in warnings).
        source: Dotted name of the module being parsed.
        index: Index of all project modules.
    """

    def __init__(self, file_path: Path, source: str, index: ProjectIndex):
        self.file_path = file_path
        self.source = source
        self.index = index
        self.is_package = file_path.name == "__init__.py"
        self.edges: list[ImportEdge] = []
        self.re_exports: list[ReExport] = []
        self.warnings: list[ParseWarning] = []

    def warn(self, code: WarningCode, line: int, detail: str) -> None:
        """Record a warning located at a line of the current file.

        Args:
            code: Kind of problem.
            line: Line number the warning refers to.
            detail: Language-neutral data describing the occurrence.
        """
        self.warnings.append(ParseWarning(code, self.file_path, line, detail))

    def add(self, name: str, symbol: str | None, line: int) -> str | None:
        """Record an import edge towards a module.

        Internal names that do not exist fall back to the closest existing
        ancestor (with a warning); self-imports produce no edge.

        Args:
            name: Dotted name of the imported module.
            symbol: Imported symbol, or None for a whole-module import.
            line: Line of the import statement.

        Returns:
            The internal target module, or None if external or unresolved.
        """
        if self.index.is_external(name):
            self.edges.append(ImportEdge(self.source, name, True, symbol, line))
            return None
        target = self.index.closest_module(name)
        if target is None:
            self.warn(WarningCode.UNRESOLVED_IMPORT, line, name)
            return None
        if target != name:
            self.warn(WarningCode.UNRESOLVED_IMPORT, line, f"{name} -> {target}")
        if target != self.source:
            self.edges.append(ImportEdge(self.source, target, False, symbol, line))
        return target

    def relative_base(self, node: ast.ImportFrom) -> str | None:
        """Return the absolute module a relative `from` import refers to.

        Args:
            node: Relative `from ... import` statement.

        Returns:
            The absolute dotted base, or None (with a warning) when the import
            goes beyond the top-level package.
        """
        package = self.source.split(".") if self.is_package else self.source.split(".")[:-1]
        up = node.level - 1
        if up >= len(package):
            relative = "." * node.level + (node.module or "")
            self.warn(WarningCode.RELATIVE_BEYOND_TOP, node.lineno, relative)
            return None
        parts = package[: len(package) - up]
        if node.module:
            parts += node.module.split(".")
        return ".".join(parts)

    def visit(self, tree: ast.Module) -> None:
        """Collect every import in a module, including nested ones, in code order.

        Args:
            tree: Parsed module.
        """
        for node in iter_statements(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.add(alias.name, None, node.lineno)
            elif isinstance(node, ast.ImportFrom):
                base = self.relative_base(node) if node.level else node.module
                if base:
                    self.visit_from(base, node)

    def visit_from(self, base: str, node: ast.ImportFrom) -> None:
        """Record the names of a `from base import ...` statement.

        A name that is a submodule of base becomes a module import; any other
        name is a symbol of base. Symbol imports in a package `__init__.py` are
        recorded as re-exports under their exported (alias) name.

        Args:
            base: Absolute dotted module the names are imported from.
            node: The `from ... import` statement.
        """
        for alias in node.names:
            if alias.name == "*":
                self.warn(WarningCode.STAR_IMPORT, node.lineno, base)
                self.add(base, None, node.lineno)
                continue
            submodule = f"{base}.{alias.name}"
            if submodule in self.index.modules:
                self.add(submodule, None, node.lineno)
                continue
            target = self.add(base, alias.name, node.lineno)
            if self.is_package and target is not None and target != self.source:
                exported = alias.asname or alias.name
                self.re_exports.append(ReExport(self.source, target, exported))


def parse_file(
    file_path: Path, name: str, index: ProjectIndex, config: AnalysisConfig
) -> FileParseResult:
    """Parse one Python file; problems become warnings instead of exceptions.

    Pure and picklable, so it can run as the unit of work of a process pool.
    Oversized files are skipped without being read.

    Args:
        file_path: Python source file.
        name: Dotted module name of the file.
        index: Index of all project modules.
        config: Analysis settings (size limit, fallback encoding).

    Returns:
        The parsed module, or None plus a warning when the file was skipped.
    """
    try:
        size = file_path.stat().st_size
        if size > config.max_file_size_bytes:
            detail = f"{size} > {config.max_file_size_bytes}"
            warning = ParseWarning(WarningCode.FILE_TOO_LARGE, file_path, None, detail)
            return FileParseResult(None, warnings=[warning])
        encoding = detect_encoding(file_path, config.default_encoding)
        tree = ast.parse(file_path.read_text(encoding=encoding), filename=str(file_path))
    except (OSError, SyntaxError, UnicodeDecodeError, RecursionError) as e:
        line = e.lineno if isinstance(e, SyntaxError) else None
        detail = f"{type(e).__name__}: {e}"
        warning = ParseWarning(WarningCode.PARSE_ERROR, file_path, line, detail)
        return FileParseResult(None, warnings=[warning])
    collector = _ImportCollector(file_path, name, index)
    collector.visit(tree)
    return FileParseResult(
        ModuleInfo(name, file_path, collector.edges), collector.re_exports, collector.warnings
    )


class PythonAdapter(LanguageAdapter):
    """Language adapter for Python, built on the standard library `ast` module.

    Args:
        config: Analysis settings; defaults are used when omitted.
    """

    def __init__(self, config: AnalysisConfig | None = None):
        self.config = config or AnalysisConfig()

    @property
    def language_name(self) -> str:
        """Name of the language this adapter handles: "python"."""
        return "python"

    @property
    def file_extensions(self) -> list[str]:
        """File extensions of Python source files."""
        return [".py"]

    def discover_files(
        self, root: Path, exclude_spec: pathspec.PathSpec, follow_symlinks: bool = False
    ) -> Iterator[Path]:
        """Yield the Python files under root that are not excluded.

        Args:
            root: Project directory to walk.
            exclude_spec: Combined exclude patterns; matching paths are skipped.
            follow_symlinks: Whether to descend into symlinked directories.

        Returns:
            An iterator over the Python files to analyze.
        """
        return walk_files(root, tuple(self.file_extensions), exclude_spec, follow_symlinks)

    def normalize_module_name(self, file_path: Path, root: Path) -> str:
        """Return the dotted module name of a file, relative to its source root.

        Args:
            file_path: Python source file.
            root: Project directory the file belongs to.

        Returns:
            The dotted module name, e.g. "pkg.core" for "src/pkg/core.py".
        """
        return module_name(file_path, resolve_source_roots(root, self.config.source_roots))

    def plan_parse(self, files: list[Path], root: Path) -> ParsePlan:
        """Name every file first, so imports can be classified against the whole project.

        Args:
            files: Python source files to parse.
            root: Project directory the files belong to.

        Returns:
            One task per file, in the given order, sharing the project index.
        """
        source_roots = resolve_source_roots(root, self.config.source_roots)
        tasks = [(path, module_name(path, source_roots)) for path in files]
        return ParsePlan(tasks, ProjectIndex.from_names({name for _, name in tasks}))

    def parse_task(self, task: ParseTask, shared: ProjectIndex) -> FileParseResult:
        """Parse one Python file against the project index.

        Args:
            task: File and module name, from `plan_parse`.
            shared: The project index built by `plan_parse`.

        Returns:
            The parsed module, or None plus a warning when the file was skipped.
        """
        path, name = task
        return parse_file(path, name, shared, self.config)
