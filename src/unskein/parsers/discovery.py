"""Find the source files to analyze: combined excludes, safe directory walk, encoding."""

import ast
import io
import os
import re
import tokenize
import warnings
from collections.abc import Callable, Hashable, Iterator, Mapping, Sequence
from fnmatch import fnmatchcase
from pathlib import Path

import pathspec

from unskein.config import AnalysisConfig

GITIGNORE_FILE = ".gitignore"
IGNORE_FILES = (GITIGNORE_FILE, ".unskeinignore")
TEST_CODE_PATTERNS = ("tests/", "test/", "test_*.py", "conftest.py")
# A suffix that usually marks a test, but sometimes production code (``quellen_test.py``).
TEST_LIKE_NAME_PATTERNS = ("*_test.py",)
DEFAULT_TEST_PATTERNS = (*TEST_CODE_PATTERNS, *TEST_LIKE_NAME_PATTERNS)
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
    test_like_names: bool = True,
) -> pathspec.PathSpec:
    """Combine every exclude source into one gitignore-style spec.

    Patterns from the default test patterns, `.gitignore`, `.unskeinignore` and
    the CLI are merged (union); none overrides another.

    Args:
        root: Project directory holding the ignore files.
        cli_exclude: Extra patterns passed with `--exclude`.
        include_tests: Whether to keep test code instead of excluding it by default.
        test_like_names: Whether the test patterns include ``*_test.py``; off when
            the caller filters those files itself with ``drop_unimported_test_files``.

    Returns:
        A spec that matches every path to leave out of the analysis.
    """
    return _spec(root, cli_exclude, include_tests, IGNORE_FILES, test_like_names)


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
    test_like_names: bool = True,
) -> pathspec.PathSpec:
    """Build a gitignore-style spec from the default test patterns, ignore files and CLI.

    Args:
        root: Project directory holding the ignore files.
        cli_exclude: Extra patterns passed with `--exclude`.
        include_tests: Whether to keep test code instead of excluding it by default.
        ignore_files: Names of the ignore files to read.
        test_like_names: Whether the test patterns include ``*_test.py``.

    Returns:
        The union of every pattern.
    """
    test_patterns = DEFAULT_TEST_PATTERNS if test_like_names else TEST_CODE_PATTERNS
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


def is_test_like_name(file_name: str) -> bool:
    """Tell whether a file is named like a test module without being one for sure.

    Args:
        file_name: Base name of the file.

    Returns:
        True when the name matches ``*_test.py``.
    """
    return any(fnmatchcase(file_name, pattern) for pattern in TEST_LIKE_NAME_PATTERNS)


def drop_unimported_test_files(files: Sequence[Path], config: AnalysisConfig) -> list[Path]:
    """Leave out the files named ``*_test.py``, except those that other code imports.

    A file named like a test that production code imports (``quellen_test.py``, a
    "source test" feature) is production code; excluding it would turn every import of
    it into an import of a module that does not exist. Imports are found by scanning the
    text of the other files, so this costs one read of each file, and only when some
    file is named like a test. The scan matches words, not modules: any word of an
    import statement equal to the file's stem keeps the file, even a trailing comment or
    a same-named module of another package. That over-inclusion is accepted; a kept
    file is a real module, only one that might have been left out.

    Args:
        files: Discovered files, with the ``*_test.py`` pattern not applied.
        config: Analysis settings; its size limit and fallback encoding apply to the
            scan exactly as to parsing.

    Returns:
        The files in the same order, without the test-named ones nothing imports.
    """
    named_like_tests = {path for path in files if is_test_like_name(path.name)}
    if not named_like_tests:
        return list(files)
    stems = {path.stem for path in named_like_tests}
    others = [path for path in files if path.suffix == ".py" and path not in named_like_tests]
    imported = _imported_names(others, stems, config)
    return [path for path in files if path not in named_like_tests or path.stem in imported]


def _imported_names(files: Sequence[Path], wanted: set[str], config: AnalysisConfig) -> set[str]:
    """Return which of the wanted names appear in an import statement of the files.

    Files over the size limit, unreadable or with an unknown encoding are skipped
    quietly: the parser reports them later.

    Args:
        files: Python source files to scan.
        wanted: Module base names to look for.
        config: Analysis settings with the size limit and the fallback encoding.

    Returns:
        The wanted names some import statement mentions.
    """
    found: set[str] = set()
    missing = set(wanted)
    needles = {name.encode("utf-8") for name in wanted}
    for path in files:
        data = _read_for_scan(path, config)
        # Source encodings are ASCII-compatible, so a byte search rules out most files
        # before anything is decoded, and it is far cheaper than the regex.
        if data is None or not any(needle in data for needle in needles):
            continue
        encoding = declared_encoding(io.BytesIO(data).readline, config.default_encoding)
        text = data.decode(encoding, errors="replace")
        for match in IMPORT_STATEMENT.finditer(text):
            for group in match.groups():
                if group:
                    found |= missing.intersection(WORD.findall(group))
        missing -= found
        needles = {name.encode("utf-8") for name in missing}
        if not missing:
            break
    return found


def _read_for_scan(path: Path, config: AnalysisConfig) -> bytes | None:
    """Read a source file under the parser's size limit, or give up quietly.

    One open per file: the size comes from the open handle, since on Windows opening a
    file costs more than reading a small one.

    Args:
        path: Python source file.
        config: Analysis settings with the size limit.

    Returns:
        The raw bytes, or None when the file is over the limit or cannot be read.
    """
    try:
        with open(path, "rb") as handle:
            if os.fstat(handle.fileno()).st_size > config.max_file_size_bytes:
                return None
            return handle.read()
    except OSError:
        return None


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
    with open(file_path, "rb") as f:
        return declared_encoding(f.readline, config_default)


def declared_encoding(readline: Callable[[], bytes], config_default: str | None) -> str:
    """Return the encoding the first lines of a Python source declare (PEP 263 or BOM).

    Args:
        readline: Reads one line of raw bytes per call, like ``BufferedReader.readline``.
        config_default: Fallback encoding from configuration, if any.

    Returns:
        The detected encoding, else the fallback, else "utf-8".
    """
    try:
        encoding, _ = tokenize.detect_encoding(readline)
    except SyntaxError:
        return config_default or "utf-8"
    return encoding


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
