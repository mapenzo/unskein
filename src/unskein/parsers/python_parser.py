import ast
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pathspec

from unskein.config import AnalysisConfig
from unskein.parsers.base import LanguageAdapter
from unskein.parsers.discovery import detect_encoding, walk_files
from unskein.parsers.models import ImportEdge, ModuleInfo, ParseResult, ReExport


@dataclass(slots=True)
class FileParseResult:
    module: ModuleInfo | None
    re_exports: list[ReExport] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ProjectIndex:
    modules: frozenset[str]
    top_level: frozenset[str]

    @classmethod
    def from_names(cls, names: set[str]) -> "ProjectIndex":
        return cls(frozenset(names), frozenset(n.split(".")[0] for n in names))

    def is_external(self, name: str) -> bool:
        return name.split(".")[0] not in self.top_level

    def closest_module(self, name: str) -> str | None:
        parts = name.split(".")
        for end in range(len(parts), 0, -1):
            candidate = ".".join(parts[:end])
            if candidate in self.modules:
                return candidate
        return None


def _absolute(path: Path) -> Path:
    # abspath, not resolve(): a followed symlink must keep its in-project link path.
    return Path(os.path.abspath(path))


def resolve_source_roots(root: Path, configured: list[str] | None) -> list[Path]:
    """Most specific first; root itself is always the last fallback."""
    if configured is None:
        src = root / "src"
        configured = ["src"] if src.is_dir() and not (src / "__init__.py").exists() else []
    roots = [_absolute(root / r) for r in configured]
    absolute_root = _absolute(root)
    if absolute_root not in roots:
        roots.append(absolute_root)
    return sorted(roots, key=lambda p: len(p.parts), reverse=True)


def module_name(file_path: Path, source_roots: list[Path]) -> str:
    absolute = _absolute(file_path)
    for source_root in source_roots:
        if absolute.is_relative_to(source_root):
            parts = list(absolute.relative_to(source_root).with_suffix("").parts)
            if parts and parts[-1] == "__init__":
                parts.pop()
            return ".".join(parts) or source_root.name
    raise ValueError(f"{file_path} is outside every source root")


class _ImportCollector:
    def __init__(self, file_path: Path, source: str, index: ProjectIndex):
        self.file_path = file_path
        self.source = source
        self.index = index
        self.is_package = file_path.name == "__init__.py"
        self.edges: list[ImportEdge] = []
        self.re_exports: list[ReExport] = []
        self.warnings: list[str] = []

    def warn(self, line: int, message: str) -> None:
        self.warnings.append(f"{self.file_path}:{line}: {message}")

    def add(self, name: str, symbol: str | None, line: int) -> str | None:
        """Record the edge; return the internal target module, or None if external/unresolved."""
        if self.index.is_external(name):
            self.edges.append(ImportEdge(self.source, name, True, symbol, line))
            return None
        target = self.index.closest_module(name)
        if target is None:
            self.warn(line, f"internal import '{name}' not found, skipped")
            return None
        if target != name:
            self.warn(line, f"internal import '{name}' not found, using '{target}'")
        if target != self.source:
            self.edges.append(ImportEdge(self.source, target, False, symbol, line))
        return target

    def relative_base(self, node: ast.ImportFrom) -> str | None:
        package = self.source.split(".") if self.is_package else self.source.split(".")[:-1]
        up = node.level - 1
        if up >= len(package):
            self.warn(node.lineno, "relative import goes beyond the top-level package")
            return None
        parts = package[: len(package) - up]
        if node.module:
            parts += node.module.split(".")
        return ".".join(parts)

    def visit(self, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.add(alias.name, None, node.lineno)
            elif isinstance(node, ast.ImportFrom):
                base = self.relative_base(node) if node.level else node.module
                if base:
                    self.visit_from(base, node)

    def visit_from(self, base: str, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "*":
                self.warn(node.lineno, f"'from {base} import *': exported names are unknown")
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
    try:
        size = file_path.stat().st_size
        if size > config.max_file_size_bytes:
            return FileParseResult(
                None,
                warnings=[
                    f"{file_path}: {size} bytes exceeds max_file_size_bytes "
                    f"({config.max_file_size_bytes}), skipped"
                ],
            )
        encoding = detect_encoding(file_path, config.default_encoding)
        tree = ast.parse(file_path.read_text(encoding=encoding), filename=str(file_path))
    except (OSError, SyntaxError, UnicodeDecodeError, RecursionError) as e:
        return FileParseResult(
            None, warnings=[f"{file_path}: could not parse ({type(e).__name__}: {e})"]
        )
    collector = _ImportCollector(file_path, name, index)
    collector.visit(tree)
    return FileParseResult(
        ModuleInfo(name, file_path, collector.edges), collector.re_exports, collector.warnings
    )


class PythonAdapter(LanguageAdapter):
    def __init__(self, config: AnalysisConfig | None = None):
        self.config = config or AnalysisConfig()

    @property
    def language_name(self) -> str:
        return "python"

    @property
    def file_extensions(self) -> list[str]:
        return [".py"]

    def discover_files(
        self, root: Path, exclude_spec: pathspec.PathSpec, follow_symlinks: bool = False
    ) -> Iterator[Path]:
        return walk_files(root, tuple(self.file_extensions), exclude_spec, follow_symlinks)

    def normalize_module_name(self, file_path: Path, root: Path) -> str:
        return module_name(file_path, resolve_source_roots(root, self.config.source_roots))

    def parse(self, files: list[Path], root: Path) -> ParseResult:
        source_roots = resolve_source_roots(root, self.config.source_roots)
        names = {path: module_name(path, source_roots) for path in files}
        index = ProjectIndex.from_names(set(names.values()))
        result = ParseResult(modules=[], language=self.language_name)
        for path, name in names.items():
            file_result = parse_file(path, name, index, self.config)
            if file_result.module is not None:
                result.modules.append(file_result.module)
            result.re_exports.extend(file_result.re_exports)
            result.warnings.extend(file_result.warnings)
        return result
