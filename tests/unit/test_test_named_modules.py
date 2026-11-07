from collections.abc import Callable
from pathlib import Path

from unskein.config import AnalysisConfig
from unskein.parsers.discovery import (
    drop_unimported_test_files,
    load_exclude_spec,
    walk_files,
)

MakeProject = Callable[[dict[str, str]], Path]


def kept(root: Path, config: AnalysisConfig | None = None) -> list[str]:
    """Discover files the way a scan does and return the kept ones, relative to root."""
    spec = load_exclude_spec(root, [], test_like_names=False)
    files = sorted(walk_files(root, (".py",), spec))
    dropped = drop_unimported_test_files(files, config or AnalysisConfig())
    return [path.relative_to(root).as_posix() for path in dropped]


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


def test_test_named_file_nothing_imports_is_dropped(make_project: MakeProject) -> None:
    root = make_project(
        {
            "web/api.py": "",
            "web/helpers_test.py": "",
            "web/test_api.py": "import helpers_test\n",
        }
    )

    assert kept(root) == ["web/api.py"]


def test_test_prefixed_file_stays_excluded_even_when_imported(
    make_project: MakeProject,
) -> None:
    root = make_project(
        {
            "app/a.py": "from app.test_b import helper\n",
            "app/test_b.py": "def helper(): ...\n",
        }
    )

    assert kept(root) == ["app/a.py"]


def test_test_directories_and_conftest_stay_excluded(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app.py": "import conftest\nfrom tests import util\n",
            "conftest.py": "",
            "tests/util.py": "",
        }
    )

    assert kept(root) == ["app.py"]


def test_importer_over_the_size_limit_is_not_read(make_project: MakeProject) -> None:
    source = "import probe_test\n"
    root = make_project({"app.py": source, "probe_test.py": ""})
    config = AnalysisConfig(max_file_size_bytes=len(source) - 1)

    assert kept(root, config) == ["app.py"]


def test_importer_is_read_with_its_declared_encoding(make_project: MakeProject) -> None:
    root = make_project({"probe_test.py": ""})
    importer = root / "app.py"
    importer.write_bytes(
        "# -*- coding: latin-1 -*-\nNAME = 'caf\xe9'\nimport probe_test\n".encode("latin-1")
    )

    assert kept(root) == ["app.py", "probe_test.py"]


def test_default_spec_still_excludes_test_like_names(make_project: MakeProject) -> None:
    root = make_project({"app.py": "import probe_test\n", "probe_test.py": ""})
    spec = load_exclude_spec(root, [])

    assert [path.name for path in walk_files(root, (".py",), spec)] == ["app.py"]
