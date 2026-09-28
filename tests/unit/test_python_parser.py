from collections.abc import Callable
from pathlib import Path

import pathspec

from unskein.config import AnalysisConfig
from unskein.parsers.discovery import detect_encoding, load_exclude_spec
from unskein.parsers.python_parser import PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]


def test_normalize_module_name_collapses_init(tmp_path: Path) -> None:
    adapter = PythonAdapter()
    assert adapter.normalize_module_name(tmp_path / "app/services/user.py", tmp_path) == (
        "app.services.user"
    )
    assert adapter.normalize_module_name(tmp_path / "app/services/__init__.py", tmp_path) == (
        "app.services"
    )


def test_src_layout_is_detected_automatically(make_project: MakeProject) -> None:
    root = make_project({"src/pkg/__init__.py": "", "src/pkg/core.py": "", "scripts/run.py": ""})
    adapter = PythonAdapter()
    assert adapter.normalize_module_name(root / "src/pkg/core.py", root) == "pkg.core"
    assert adapter.normalize_module_name(root / "src/pkg/__init__.py", root) == "pkg"
    assert adapter.normalize_module_name(root / "scripts/run.py", root) == "scripts.run"


def test_src_dir_that_is_a_package_is_not_a_source_root(make_project: MakeProject) -> None:
    root = make_project({"src/__init__.py": "", "src/core.py": ""})
    assert PythonAdapter().normalize_module_name(root / "src/core.py", root) == "src.core"


def test_configured_source_roots_override_detection(make_project: MakeProject) -> None:
    root = make_project({"lib/pkg/a.py": "", "src/other/b.py": "", "tools/t.py": ""})
    adapter = PythonAdapter(AnalysisConfig(source_roots=["lib"]))
    assert adapter.normalize_module_name(root / "lib/pkg/a.py", root) == "pkg.a"
    assert adapter.normalize_module_name(root / "src/other/b.py", root) == "src.other.b"
    assert adapter.normalize_module_name(root / "tools/t.py", root) == "tools.t"


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


TEST_LAYOUT = {
    "pkg/__init__.py": "",
    "pkg/testing.py": "",
    "pkg/latest.py": "",
    "pkg/test_core.py": "",
    "pkg/core_test.py": "",
    "tests/unit/test_x.py": "",
    "tests/helpers.py": "",
    "test/legacy.py": "",
    "conftest.py": "",
}


def discovered(root: Path, include_tests: bool) -> list[str]:
    spec = load_exclude_spec(root, [], include_tests=include_tests)
    return sorted(
        p.relative_to(root).as_posix() for p in PythonAdapter().discover_files(root, spec)
    )


def test_test_code_is_excluded_by_default(make_project: MakeProject) -> None:
    root = make_project(TEST_LAYOUT)
    assert discovered(root, include_tests=False) == [
        "pkg/__init__.py",
        "pkg/latest.py",
        "pkg/testing.py",
    ]


def test_include_tests_keeps_test_code(make_project: MakeProject) -> None:
    root = make_project(TEST_LAYOUT)
    assert discovered(root, include_tests=True) == sorted(TEST_LAYOUT)


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
