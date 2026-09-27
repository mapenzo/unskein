import ast
from collections.abc import Iterator
from pathlib import Path

import pathspec

from unskein.parsers.base import ImportEdge, LanguageAdapter, ParseResult
from unskein.parsers.discovery import walk_files


class PythonAdapter(LanguageAdapter):
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
        parts = list(file_path.relative_to(root).with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    def parse(self, files: list[Path], root: Path) -> ParseResult:
        """ast.walk per file; SyntaxError/RecursionError/UnicodeDecodeError -> warning."""
        raise NotImplementedError

    def _extract_imports(
        self, tree: ast.Module, module_name: str, project_modules: set[str]
    ) -> list[ImportEdge]:
        raise NotImplementedError
