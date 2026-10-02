"""Define the contract every language adapter implements to join the pipeline."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pathspec

from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import FileParseResult, ParsePlan, ParseResult, ParseTask


class LanguageAdapter(ABC):
    """Discover, parse and name the source files of one programming language.

    Each language implements discovery, parsing and module naming; re-export
    resolution is shared because following a re-export chain is a graph problem
    that is the same in every language.
    """

    @property
    @abstractmethod
    def language_name(self) -> str:
        """Name of the language this adapter handles, e.g. "python"."""

    @property
    @abstractmethod
    def file_extensions(self) -> list[str]:
        """File extensions (with leading dot) that belong to this language."""

    @abstractmethod
    def discover_files(
        self, root: Path, exclude_spec: pathspec.PathSpec, follow_symlinks: bool = False
    ) -> Iterator[Path]:
        """Yield the source files under the project root that should be analyzed.

        Args:
            root: Project directory to walk.
            exclude_spec: Combined exclude patterns; matching paths are skipped.
            follow_symlinks: Whether to descend into symlinked directories.

        Returns:
            An iterator over the paths of the files to analyze.
        """

    @abstractmethod
    def plan_parse(self, files: list[Path], root: Path) -> ParsePlan:
        """Name every file and gather what all of them need to be parsed.

        Args:
            files: Source files to parse, as returned by `discover_files`.
            root: Project directory the files belong to.

        Returns:
            The tasks, in the order results are combined, plus the shared data.
        """

    @abstractmethod
    def parse_task(self, task: ParseTask, shared: Any) -> FileParseResult:
        """Parse one file; problems become warnings instead of exceptions.

        Must be pure and picklable, so it can run in a worker process.

        Args:
            task: File and module name, from `plan_parse`.
            shared: The plan's shared data.

        Returns:
            The parsed module, or None plus a warning when the file was skipped.
        """

    def parse(self, files: list[Path], root: Path) -> ParseResult:
        """Extract modules, imports and re-exports from the given files, sequentially.

        Args:
            files: Source files to parse, as returned by `discover_files`.
            root: Project directory the files belong to.

        Returns:
            The parsed modules plus any per-file warnings.
        """
        plan = self.plan_parse(files, root)
        return ParseResult.from_file_results(
            self.language_name,
            (self.parse_task(task, plan.shared) for task in plan.tasks),
            plan=plan,
        )

    @abstractmethod
    def normalize_module_name(self, file_path: Path, root: Path) -> str:
        """Return the dotted module name of a source file.

        Args:
            file_path: Source file to name.
            root: Project directory the file belongs to.

        Returns:
            The module name, e.g. "app.services.user".
        """

    def resolve_indirection(self, result: ParseResult) -> ParseResult:
        """Point symbol imports that go through re-exports at the defining module.

        Args:
            result: Parse result whose imports should be resolved.

        Returns:
            A new parse result with resolved import targets.
        """
        return resolve_indirection(result)
