from pathlib import Path

import pathspec

from unskein.parsers.discovery import detect_encoding, load_exclude_spec
from unskein.parsers.python_parser import PythonAdapter


def test_normalize_module_name_collapses_init(tmp_path: Path) -> None:
    adapter = PythonAdapter()
    assert adapter.normalize_module_name(tmp_path / "app/services/user.py", tmp_path) == (
        "app.services.user"
    )
    assert adapter.normalize_module_name(tmp_path / "app/services/__init__.py", tmp_path) == (
        "app.services"
    )


def test_discover_files_finds_all_py_files(simple_project: Path) -> None:
    files = PythonAdapter().discover_files(simple_project, pathspec.PathSpec([]))
    rel = sorted(p.relative_to(simple_project).as_posix() for p in files)
    assert rel == [
        "app/__init__.py",
        "app/main.py",
        "app/models.py",
        "app/services/__init__.py",
        "app/services/user.py",
    ]


def test_discover_files_merges_unskeinignore_and_cli_excludes(tmp_path: Path) -> None:
    for name in ("keep.py", "generated.py", "skip_cli.py"):
        (tmp_path / name).write_text("")
    (tmp_path / ".unskeinignore").write_text("generated.py\n")
    spec = load_exclude_spec(tmp_path, ["skip_cli.py"])
    files = [p.name for p in PythonAdapter().discover_files(tmp_path, spec)]
    assert files == ["keep.py"]


def test_discover_files_does_not_follow_symlinks_by_default(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.py").write_text("")
    project = tmp_path / "project"
    project.mkdir()
    (project / "own.py").write_text("")
    (project / "link").symlink_to(outside, target_is_directory=True)
    (project / "loop").symlink_to(project, target_is_directory=True)

    default = [p.name for p in PythonAdapter().discover_files(project, pathspec.PathSpec([]))]
    assert default == ["own.py"]

    followed = sorted(
        p.name
        for p in PythonAdapter().discover_files(
            project, pathspec.PathSpec([]), follow_symlinks=True
        )
    )
    assert followed == ["leak.py", "own.py"]


def test_detect_encoding_respects_pep263_cookie(tmp_path: Path) -> None:
    f = tmp_path / "latin.py"
    f.write_bytes(b"# -*- coding: latin-1 -*-\nx = '\xe9'\n")
    assert detect_encoding(f, config_default="utf-8") == "iso-8859-1"
