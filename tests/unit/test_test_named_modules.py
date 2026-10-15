from collections.abc import Callable
from pathlib import Path

from unskein.parsers.discovery import (
    drop_unimported_test_files,
    load_exclude_spec,
    walk_files,
)

MakeProject = Callable[[dict[str, str]], Path]


def kept(root: Path) -> list[str]:
    """Discover files the way a scan does and return the kept ones, relative to root."""
    spec = load_exclude_spec(root, [], test_file_names=False)
    files = sorted(walk_files(root, (".py",), spec))
    return [path.relative_to(root).as_posix() for path in drop_unimported_test_files(files)]


def test_test_named_module_that_production_code_imports_is_kept(
    make_project: MakeProject,
) -> None:
    root = make_project(
        {
            "web/api.py": "from web.quellen_test import router\n",
            "web/quellen_test.py": "router = None\n",
            "web/test_api.py": "def test_router(): ...\n",
        }
    )

    assert kept(root) == ["web/api.py", "web/quellen_test.py"]


def test_name_inside_a_parenthesized_import_counts(make_project: MakeProject) -> None:
    root = make_project(
        {
            "web/api.py": "from web import (\n    other,\n    probe_test,\n)\n",
            "web/probe_test.py": "",
        }
    )

    assert "web/probe_test.py" in kept(root)


def test_test_named_file_imported_only_by_tests_is_dropped(make_project: MakeProject) -> None:
    root = make_project(
        {
            "web/api.py": "",
            "web/helpers_test.py": "",
            "web/test_api.py": "import helpers_test\n",
        }
    )

    assert kept(root) == ["web/api.py"]


def test_test_directories_and_conftest_stay_excluded(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app.py": "import conftest\nfrom tests import util\n",
            "conftest.py": "",
            "tests/util.py": "",
        }
    )

    assert kept(root) == ["app.py"]


def test_default_spec_still_excludes_test_file_names(make_project: MakeProject) -> None:
    root = make_project({"app.py": "import probe_test\n", "probe_test.py": ""})
    spec = load_exclude_spec(root, [])

    assert [path.name for path in walk_files(root, (".py",), spec)] == ["app.py"]
