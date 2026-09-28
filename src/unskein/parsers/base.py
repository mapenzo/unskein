from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

import pathspec

from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import ParseResult


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
        return resolve_indirection(result)
