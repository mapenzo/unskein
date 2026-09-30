import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pathspec
import pytest

from unskein.parsers.discovery import load_exclude_spec, walk_files

PYTHON_EXTENSIONS = (".py",)


def relative_files(root: Path, spec: pathspec.PathSpec) -> set[str]:
    """Return the posix paths, relative to root, that ``walk_files`` yields."""
    files = walk_files(root, PYTHON_EXTENSIONS, spec)
    return {path.relative_to(root).as_posix() for path in files}


@pytest.fixture
def visited_dirs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every directory ``os.walk`` enters while ``walk_files`` runs.

    Args:
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        The list that fills up with each visited directory path.
    """
    visited: list[str] = []
    real_walk = os.walk

    def recording_walk(top: Path, **kwargs: object) -> Iterator[tuple[str, list[str], list[str]]]:
        for entry in real_walk(top, **kwargs):  # type: ignore[arg-type]
            visited.append(entry[0])
            yield entry

    monkeypatch.setattr("unskein.parsers.discovery.os.walk", recording_walk)
    return visited


def test_walk_does_not_descend_into_ignored_directories(
    make_project: Callable[[dict[str, str]], Path], visited_dirs: list[str]
) -> None:
    root = make_project({".gitignore": ".venv/\n", "app.py": "", ".venv/lib/dep.py": ""})
    spec = load_exclude_spec(root, [])
    assert relative_files(root, spec) == {"app.py"}
    assert not any(".venv" in visited for visited in visited_dirs)


@pytest.mark.parametrize("pattern", ["build", "build/", "build/**/", "**/build/"])
def test_directory_patterns_prune_the_same_files(
    make_project: Callable[[dict[str, str]], Path], pattern: str
) -> None:
    root = make_project({"app.py": "", "build/gen.py": "", "pkg/build/gen.py": "", "pkg/ok.py": ""})
    spec = load_exclude_spec(root, [pattern])
    assert "build/gen.py" not in relative_files(root, spec)
    assert "pkg/ok.py" in relative_files(root, spec)


def test_file_only_pattern_does_not_prune_directories(
    make_project: Callable[[dict[str, str]], Path],
) -> None:
    root = make_project({"app.py": "", "pkg/skip_me.py": "", "pkg/keep.py": ""})
    spec = load_exclude_spec(root, ["skip_me.py"])
    assert relative_files(root, spec) == {"app.py", "pkg/keep.py"}


def test_negated_file_inside_ignored_directory_is_not_analyzed(
    make_project: Callable[[dict[str, str]], Path],
) -> None:
    root = make_project({"app.py": "", "build/gen.py": "", "build/keep.py": ""})
    spec = load_exclude_spec(root, ["build/", "!build/keep.py"])
    assert relative_files(root, spec) == {"app.py"}


def test_default_test_directories_are_pruned(
    make_project: Callable[[dict[str, str]], Path], visited_dirs: list[str]
) -> None:
    root = make_project({"app.py": "", "tests/a.py": "", "test/b.py": ""})
    spec = load_exclude_spec(root, [])
    assert relative_files(root, spec) == {"app.py"}
    assert not any(Path(visited).name in {"tests", "test"} for visited in visited_dirs)


def test_include_tests_keeps_the_test_directories(
    make_project: Callable[[dict[str, str]], Path],
) -> None:
    root = make_project({"app.py": "", "tests/a.py": ""})
    spec = load_exclude_spec(root, [], include_tests=True)
    assert relative_files(root, spec) == {"app.py", "tests/a.py"}


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("migrations/", {"app/models.py"}),
        ("**/migrations/**", {"app/models.py"}),
        ("migrations/**", {"app/models.py", "app/migrations/0001.py"}),
    ],
)
def test_exclude_pattern_reaches_nested_migrations_only_when_not_root_anchored(
    make_project: Callable[[dict[str, str]], Path], pattern: str, expected: set[str]
) -> None:
    root = make_project(
        {"migrations/0001.py": "", "app/migrations/0001.py": "", "app/models.py": ""}
    )
    spec = load_exclude_spec(root, [pattern])
    assert relative_files(root, spec) == expected
