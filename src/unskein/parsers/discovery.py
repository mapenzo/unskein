"""Find the source files to analyze: combined excludes, safe directory walk, encoding."""

import os
import tokenize
from collections.abc import Hashable, Iterator
from pathlib import Path

import pathspec

IGNORE_FILES = (".gitignore", ".unskeinignore")
DEFAULT_TEST_PATTERNS = ("tests/", "test/", "test_*.py", "*_test.py", "conftest.py")


def load_exclude_spec(
    root: Path, cli_exclude: list[str], include_tests: bool = False
) -> pathspec.PathSpec:
    """Combine every exclude source into one gitignore-style spec.

    Patterns from the default test patterns, `.gitignore`, `.unskeinignore` and
    the CLI are merged (union); none overrides another.

    Args:
        root: Project directory holding the ignore files.
        cli_exclude: Extra patterns passed with `--exclude`.
        include_tests: Whether to keep test code instead of excluding it by default.

    Returns:
        A spec that matches every path to leave out of the analysis.
    """
    patterns: list[str] = [] if include_tests else list(DEFAULT_TEST_PATTERNS)
    for name in IGNORE_FILES:
        ignore_file = root / name
        if ignore_file.exists():
            patterns += ignore_file.read_text(encoding="utf-8").splitlines()
    patterns += cli_exclude
    return pathspec.GitIgnoreSpec.from_lines(patterns)


def _prune_excluded_dirs(
    relative_dir: str, dirnames: list[str], exclude_spec: pathspec.PathSpec
) -> None:
    """Remove excluded directories from an ``os.walk`` listing, in place.

    Mutating ``dirnames`` is the only way to stop ``os.walk`` from descending.
    Like git, an excluded directory is never re-included by a negated pattern
    for a file inside it.

    Args:
        relative_dir: Directory being listed, relative to the root, in posix form.
        dirnames: Subdirectory names of that directory; excluded ones are removed.
        exclude_spec: Paths matching it (relative to root) are skipped.
    """
    prefix = "" if relative_dir == "." else f"{relative_dir}/"
    dirnames[:] = [d for d in dirnames if not exclude_spec.match_file(f"{prefix}{d}/")]


def _directory_identity(dirpath: str) -> Hashable:
    """Return a key that is equal for every path leading to the same directory.

    ``os.stat`` follows symlinks, so it identifies the real directory much
    more cheaply than ``Path.resolve``. Where the filesystem reports no inode
    numbers (``st_ino`` is 0) every directory would look the same, so the
    resolved path is used instead.

    Args:
        dirpath: Directory reached by the walk.

    Returns:
        ``(st_dev, st_ino)``, or the resolved path when there is no inode.
    """
    stat = os.stat(dirpath)
    if stat.st_ino == 0:
        return Path(dirpath).resolve()
    return (stat.st_dev, stat.st_ino)


def walk_files(
    root: Path,
    extensions: tuple[str, ...],
    exclude_spec: pathspec.PathSpec,
    follow_symlinks: bool = False,
) -> Iterator[Path]:
    """Yield the files under root with the given extensions that are not excluded.

    Excluded directories are pruned, never entered. When symlinks are followed,
    every real directory is visited at most once, so symlink loops cannot cause
    an endless walk. Without following them no loop is possible and no check runs.

    Args:
        root: Project directory to walk.
        extensions: File suffixes to keep, e.g. (".py",).
        exclude_spec: Paths matching it (relative to root) are skipped.
        follow_symlinks: Whether to descend into symlinked directories.

    Yields:
        Each matching file path, as the walk reaches it.
    """
    # os.walk instead of Path.rglob: rglob always follows symlinks on 3.12.
    visited_directories: set[Hashable] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        if follow_symlinks:
            identity = _directory_identity(dirpath)
            if identity in visited_directories:
                dirnames.clear()
                continue
            visited_directories.add(identity)
        relative_dir = Path(dirpath).relative_to(root).as_posix()
        _prune_excluded_dirs(relative_dir, dirnames, exclude_spec)
        for fname in filenames:
            if fname.endswith(extensions):
                full = Path(dirpath, fname)
                if not exclude_spec.match_file(full.relative_to(root).as_posix()):
                    yield full


def detect_encoding(file_path: Path, config_default: str | None) -> str:
    """Return the encoding a Python file declares (PEP 263 cookie or BOM).

    The configured default is only a fallback for files whose encoding cannot be
    detected; it never overrides an explicit declaration.

    Args:
        file_path: Python source file to inspect.
        config_default: Fallback encoding from configuration, if any.

    Returns:
        The detected encoding, else the fallback, else "utf-8".
    """
    try:
        with open(file_path, "rb") as f:
            encoding, _ = tokenize.detect_encoding(f.readline)
        return encoding
    except SyntaxError:
        return config_default or "utf-8"
