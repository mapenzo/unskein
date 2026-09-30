import os
from pathlib import Path
from types import SimpleNamespace

import pathspec
import pytest

from unskein.parsers.discovery import walk_files

PYTHON_EXTENSIONS = (".py",)
EMPTY_SPEC = pathspec.PathSpec([])


def relative_files(root: Path, follow_symlinks: bool) -> list[str]:
    """Return the sorted posix paths, relative to root, that ``walk_files`` yields."""
    files = walk_files(root, PYTHON_EXTENSIONS, EMPTY_SPEC, follow_symlinks)
    return sorted(path.relative_to(root).as_posix() for path in files)


def test_walk_does_not_resolve_directories_when_symlinks_are_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pkg" / "sub").mkdir(parents=True)
    (tmp_path / "pkg" / "sub" / "mod.py").write_text("")
    resolved: list[Path] = []
    real_resolve = Path.resolve

    def recording_resolve(self: Path, strict: bool = False) -> Path:
        resolved.append(self)
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", recording_resolve)
    assert relative_files(tmp_path, follow_symlinks=False) == ["pkg/sub/mod.py"]
    assert not resolved


def test_symlink_loop_between_sibling_directories_is_walked_once(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "in_a.py").write_text("")
    (tmp_path / "b" / "in_b.py").write_text("")
    (tmp_path / "a" / "link_b").symlink_to(tmp_path / "b", target_is_directory=True)
    (tmp_path / "b" / "link_a").symlink_to(tmp_path / "a", target_is_directory=True)
    files = relative_files(tmp_path, follow_symlinks=True)
    assert sorted(Path(f).name for f in files) == ["in_a.py", "in_b.py"]


def test_zero_inode_falls_back_to_the_resolved_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("one", "two"):
        (tmp_path / name).mkdir()
        (tmp_path / name / f"{name}.py").write_text("")
    real_stat = os.stat

    def stat_without_inodes(path: str) -> SimpleNamespace:
        return SimpleNamespace(st_dev=real_stat(path).st_dev, st_ino=0)

    # Replace only the `os` seen by discovery: patching `os.stat` itself would
    # also break pathlib and pytest, which need the full stat result.
    discovery_os = SimpleNamespace(walk=os.walk, stat=stat_without_inodes)
    monkeypatch.setattr("unskein.parsers.discovery.os", discovery_os)
    assert relative_files(tmp_path, follow_symlinks=True) == ["one/one.py", "two/two.py"]
