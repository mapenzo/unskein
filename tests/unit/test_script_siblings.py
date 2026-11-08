from collections.abc import Callable
from pathlib import Path

import pathspec

from unskein.config import AnalysisConfig
from unskein.parsers.python_parser import PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]
EMPTY_SPEC = pathspec.PathSpec([])


def edges(root: Path, config: AnalysisConfig | None = None) -> set[tuple[str, str, bool]]:
    """Parse a project the way a scan does and return its (source, target, external) edges."""
    adapter = PythonAdapter(config)
    files = list(adapter.discover_files(root, EMPTY_SPEC))
    plan = adapter.plan_parse(files, root)
    found = set()
    for task in plan.tasks:
        module = adapter.parse_task(task, plan.shared).module
        assert module is not None
        found |= {(e.source, e.target, e.is_external) for e in module.imports}
    return found


def test_script_imports_a_sibling_file_in_a_directory_without_init(
    make_project: MakeProject,
) -> None:
    root = make_project(
        {
            "tools/skripte/run.py": "import zweifel\nfrom regeln import VERSION\n",
            "tools/skripte/zweifel.py": "",
            "tools/skripte/regeln.py": "VERSION = 1\n",
        }
    )

    found = edges(root)

    assert ("tools.skripte.run", "tools.skripte.zweifel", False) in found
    assert ("tools.skripte.run", "tools.skripte.regeln", False) in found


def test_sibling_package_with_submodule_resolves(make_project: MakeProject) -> None:
    root = make_project(
        {
            "tools/run.py": "from helpers.io import read\n",
            "tools/helpers/__init__.py": "",
            "tools/helpers/io.py": "def read(): ...\n",
        }
    )

    assert ("tools.run", "tools.helpers.io", False) in edges(root)


def test_import_without_a_sibling_stays_external(make_project: MakeProject) -> None:
    root = make_project({"tools/run.py": "import requests\n", "tools/other.py": ""})

    assert ("tools.run", "requests", True) in edges(root)


def test_module_of_a_regular_package_does_not_import_siblings_absolutely(
    make_project: MakeProject,
) -> None:
    root = make_project(
        {
            "pkg/__init__.py": "",
            "pkg/run.py": "import helper\n",
            "pkg/helper.py": "",
        }
    )

    assert ("pkg.run", "helper", True) in edges(root)


def test_import_that_already_resolves_in_the_project_is_left_alone(
    make_project: MakeProject,
) -> None:
    root = make_project(
        {
            "core/__init__.py": "",
            "tools/run.py": "import core\n",
            "tools/core.py": "",
        }
    )

    assert ("tools.run", "core", False) in edges(root)


def test_script_resolves_a_sibling_and_a_package_alias_in_the_same_project(
    make_project: MakeProject,
) -> None:
    root = make_project(
        {
            "verwaltung/__init__.py": "",
            "verwaltung/admin_web/__init__.py": "",
            "verwaltung/admin_web/api.py": "",
            "tools/run.py": "import helper\nimport admin_web.api\nfrom admin_web import api\n",
            "tools/helper.py": "",
        }
    )
    config = AnalysisConfig(module_aliases={"admin_web": "verwaltung.admin_web"})

    found = edges(root, config)

    assert ("tools.run", "tools.helper", False) in found
    assert ("tools.run", "verwaltung.admin_web.api", False) in found
    assert not {target for _, target, _ in found if target.startswith("admin_web")}
