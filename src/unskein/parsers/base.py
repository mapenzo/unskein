from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pathspec


@dataclass(slots=True)
class ImportEdge:
    source: str
    target: str
    is_external: bool
    symbol_name: str | None = None
    line_number: int | None = None


@dataclass(slots=True)
class ModuleInfo:
    name: str
    file_path: Path
    imports: list[ImportEdge] = field(default_factory=list)


@dataclass(slots=True)
class ReExport:
    exporting_module: str
    original_module: str
    symbol_name: str


@dataclass
class ParseResult:
    modules: list[ModuleInfo]
    language: str
    re_exports: list[ReExport] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class LanguageAdapter(ABC):
    @property
    @abstractmethod
    def language_name(self) -> str: ...

    @property
    @abstractmethod
    def file_extensions(self) -> list[str]: ...

    @abstractmethod
    def discover_files(
        self, root: Path, exclude_spec: pathspec.PathSpec, follow_symlinks: bool = False
    ) -> Iterator[Path]: ...

    @abstractmethod
    def parse(self, files: list[Path], root: Path) -> ParseResult: ...

    @abstractmethod
    def normalize_module_name(self, file_path: Path, root: Path) -> str: ...

    def resolve_indirection(self, result: ParseResult) -> ParseResult:
        from unskein.parsers.indirection import resolve_indirection

        return resolve_indirection(result)
