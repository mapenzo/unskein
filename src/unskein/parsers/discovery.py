"""Find the source files to analyze: combined excludes, safe directory walk, encoding."""

import ast
import os
import re
import tokenize
import warnings
from collections.abc import Hashable, Iterator, Mapping, Sequence
from fnmatch import fnmatchcase
from pathlib import Path

import pathspec

GITIGNORE_FILE = ".gitignore"
IGNORE_FILES = (GITIGNORE_FILE, ".unskeinignore")
TEST_DIRECTORY_PATTERNS = ("tests/", "test/", "conftest.py")
# File names that usually hold tests, but sometimes production code (``quellen_test.py``).
TEST_FILE_NAME_PATTERNS = ("test_*.py", "*_test.py")
DEFAULT_TEST_PATTERNS = (*TEST_DIRECTORY_PATTERNS, *TEST_FILE_NAME_PATTERNS)
# The names an import statement mentions: ``from a.b import (c, d)`` or ``import a.b as c``.
IMPORT_STATEMENT = re.compile(
    r"^[ \t]*(?:from[ \t]+([\w.]+)[ \t]+import[ \t]*(\([^)]*\)|[^\n]*)|import[ \t]+([^\n]*))",
    re.MULTILINE,
)
WORD = re.compile(r"\w+")


def load_exclude_spec(
    root: Path,
    cli_exclude: list[str],
    include_tests: bool = False,
    *,
    test_file_names: bool = True,
) -> pathspec.PathSpec:
    """Combine every exclude source into one gitignore-style spec.

    Patterns from the default test patterns, `.gitignore`, `.unskeinignore` and
    the CLI are merged (union); none overrides another.

    Args:
        root: Project directory holding the ignore files.
        cli_exclude: Extra patterns passed with `--exclude`.
        include_tests: Whether to keep test code instead of excluding it by default.
        test_file_names: Whether the test patterns include the file-name ones
            (``test_*.py``, ``*_test.py``); off when the caller filters those files
            itself with ``drop_unimported_test_files``.

    Returns:
        A spec that matches every path to leave out of the analysis.
    """
    return _spec(root, cli_exclude, include_tests, IGNORE_FILES, test_file_names)


def load_evidence_spec(
    root: Path, cli_exclude: list[str], include_tests: bool = False
) -> pathspec.PathSpec:
    """Combine the exclude sources that apply to stubs and binaries: all but ``.gitignore``.

    A binary built in place is usually git-ignored (``*.so``), yet it proves its module
    exists. ``.unskeinignore`` and ``--exclude`` still leave it out.

    Args:
        root: Project directory holding the ignore files.
        cli_exclude: Extra patterns passed with `--exclude`.
        include_tests: Whether to keep test code instead of excluding it by default.

    Returns:
        A spec that matches every stub or binary to leave out of the analysis.
    """
    ignore_files = tuple(name for name in IGNORE_FILES if name != GITIGNORE_FILE)
    return _spec(root, cli_exclude, include_tests, ignore_files)


def _spec(
    root: Path,
    cli_exclude: list[str],
    include_tests: bool,
    ignore_files: tuple[str, ...],
    test_file_names: bool = True,
) -> pathspec.PathSpec:
    """Build a gitignore-style spec from the default test patterns, ignore files and CLI.

    Args:
        root: Project directory holding the ignore files.
        cli_exclude: Extra patterns passed with `--exclude`.
        include_tests: Whether to keep test code instead of excluding it by default.
        ignore_files: Names of the ignore files to read.
        test_file_names: Whether the test patterns include the file-name ones.

    Returns:
        The union of every pattern.
    """
    test_patterns = DEFAULT_TEST_PATTERNS if test_file_names else TEST_DIRECTORY_PATTERNS
    patterns: list[str] = [] if include_tests else list(test_patterns)
    for name in ignore_files:
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
    *,
    file_specs: Mapping[str, pathspec.PathSpec] | None = None,
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
        file_specs: Spec to match files of a suffix against instead of ``exclude_spec``
            (directories are always pruned with ``exclude_spec``).

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
                spec = file_specs.get(full.suffix, exclude_spec) if file_specs else exclude_spec
                if not spec.match_file(full.relative_to(root).as_posix()):
                    yield full


def is_test_file_name(file_name: str) -> bool:
    """Tell whether a file is named like a test module (``test_*.py``, ``*_test.py``).

    Args:
        file_name: Base name of the file.

    Returns:
        True when the name matches a test file-name pattern.
    """
    return any(fnmatchcase(file_name, pattern) for pattern in TEST_FILE_NAME_PATTERNS)


def drop_unimported_test_files(files: Sequence[Path]) -> list[Path]:
    """Leave out the files named like tests, except those that other code imports.

    A file named like a test that production code imports (``quellen_test.py``, a
    "source test" feature) is production code; excluding it would turn every import of
    it into an import of a module that does not exist. Imports are found by scanning the
    text of the other files, so this costs one read of each file, and only when some
    file is named like a test.

    Args:
        files: Discovered files, with the file-name test patterns not applied.

    Returns:
        The files in the same order, without the test-named ones nothing imports.
    """
    named_like_tests = {path for path in files if is_test_file_name(path.name)}
    if not named_like_tests:
        return list(files)
    stems = {path.stem for path in named_like_tests}
    others = [path for path in files if path.suffix == ".py" and path not in named_like_tests]
    imported = _imported_names(others, stems)
    return [path for path in files if path not in named_like_tests or path.stem in imported]


def _imported_names(files: Sequence[Path], wanted: set[str]) -> set[str]:
    """Return which of the wanted names appear in an import statement of the files.

    Args:
        files: Python source files to scan.
        wanted: Module base names to look for.

    Returns:
        The wanted names some import statement mentions.
    """
    found: set[str] = set()
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in IMPORT_STATEMENT.finditer(text):
            for group in match.groups():
                if group:
                    found |= wanted.intersection(WORD.findall(group))
        if found == wanted:
            break
    return found


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


def parse_source(file_path: Path, encoding: str | None) -> ast.Module | None:
    """Read and parse a source file again, or give up quietly.

    Args:
        file_path: Python source file.
        encoding: Fallback encoding when the file declares none.

    Returns:
        The parsed module, or None when the file cannot be read or parsed any more.
    """
    try:
        source = file_path.read_text(encoding=detect_encoding(file_path, encoding))
        with warnings.catch_warnings():
            # The scan already reported these; repeating them on this on-demand path is noise.
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(source, filename=str(file_path))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError, RecursionError, LookupError):
        return None
