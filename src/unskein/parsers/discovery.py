import os
import tokenize
from collections.abc import Iterator
from pathlib import Path

import pathspec

IGNORE_FILES = (".gitignore", ".unskeinignore")


def load_exclude_spec(root: Path, cli_exclude: list[str]) -> pathspec.PathSpec:
    patterns: list[str] = []
    for name in IGNORE_FILES:
        ignore_file = root / name
        if ignore_file.exists():
            patterns += ignore_file.read_text(encoding="utf-8").splitlines()
    patterns += cli_exclude
    return pathspec.GitIgnoreSpec.from_lines(patterns)


def walk_files(
    root: Path,
    extensions: tuple[str, ...],
    exclude_spec: pathspec.PathSpec,
    follow_symlinks: bool = False,
) -> Iterator[Path]:
    # os.walk instead of Path.rglob: rglob always follows symlinks on 3.12.
    visited_real_dirs: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        real = Path(dirpath).resolve()
        if real in visited_real_dirs:
            dirnames.clear()
            continue
        visited_real_dirs.add(real)
        for fname in filenames:
            if fname.endswith(extensions):
                full = Path(dirpath, fname)
                if not exclude_spec.match_file(full.relative_to(root).as_posix()):
                    yield full


def detect_encoding(file_path: Path, config_default: str | None) -> str:
    try:
        with open(file_path, "rb") as f:
            encoding, _ = tokenize.detect_encoding(f.readline)
        return encoding
    except SyntaxError:
        return config_default or "utf-8"
