from collections.abc import Callable
from pathlib import Path

from unskein.config import AnalysisConfig
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import WarningCode
from unskein.parsers.python_parser import ProjectIndex, PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]


def _parse(root: Path):
    """Parse every .py file under root."""
    return PythonAdapter(AnalysisConfig()).parse(sorted(root.rglob("*.py")), root)


def _imports(result, module: str) -> list:
    """Return the internal import edges of one module."""
    (found,) = [m for m in result.modules if m.name == module]
    return [edge for edge in found.imports if not edge.is_external]


def test_prefixes_that_are_not_modules_are_namespaces() -> None:
    index = ProjectIndex.from_names({"app", "app.types.models", "app.types.llms.openai"})
    assert index.namespaces == frozenset({"app.types", "app.types.llms"})
    assert index.is_namespace("app.types")
    assert not index.is_namespace("app")
    assert {"app.types", "app.types.llms"} <= index.modules
    assert index.is_package("app.types")


def test_top_level_prefix_without_module_is_a_namespace() -> None:
    index = ProjectIndex.from_names({"acme.billing.api"})
    assert index.namespaces == frozenset({"acme", "acme.billing"})


def test_path_names_make_no_namespaces() -> None:
    index = ProjectIndex.from_names({"app", ".circleci/scripts/run.py", "tool-x/a.b.py"})
    assert index.namespaces == frozenset()


def test_import_of_a_namespace_is_exact_and_silent(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/types/models.py": "",
            "app/core.py": "import app.types\n",
        }
    )
    result = _parse(root)
    assert [e.target for e in _imports(result, "app.core")] == ["app.types"]
    assert [e.requested for e in _imports(result, "app.core")] == [None]
    assert not [w for w in result.warnings if w.code is WarningCode.UNRESOLVED_IMPORT]


def test_from_import_of_a_namespace_is_a_module_import(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/types/models.py": "",
            "app/core.py": "from app import types\n",
        }
    )
    (edge,) = _imports(_parse(root), "app.core")
    assert (edge.target, edge.symbol_name) == ("app.types", None)


def test_missing_module_falls_back_to_its_namespace_and_keeps_the_name(
    make_project: MakeProject,
) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/types/models.py": "",
            "app/core.py": "from app.types.gone import x\n",
        }
    )
    result = _parse(root)
    (edge,) = _imports(result, "app.core")
    assert (edge.target, edge.requested) == ("app.types", "app.types.gone")
    (warning,) = [w for w in result.warnings if w.code is WarningCode.UNRESOLVED_IMPORT]
    assert warning.detail == "app.types.gone -> app.types"


def _resolved_targets(root: Path, module: str) -> list[str]:
    """Return the sorted internal targets of a module after re-export resolution."""
    result = resolve_indirection(_parse(root))
    return sorted(e.target for e in _imports(result, module))


def test_namespace_import_expands_to_the_modules_read(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/types/models.py": "class Model: ...\n",
            "app/types/llms/openai.py": "class OpenAI: ...\n",
            "app/core.py": "import app\nimport app.types\nimport app.types.llms\n"
            "def f():\n    return app.types.models.Model(), app.types.llms.openai.OpenAI()\n",
        }
    )
    assert _resolved_targets(root, "app.core") == [
        "app",
        "app.types.llms.openai",
        "app.types.models",
    ]


def test_regular_package_import_expands_too(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/sub/__init__.py": "",
            "app/sub/leaf.py": "def f(): ...\n",
            "app/core.py": "import app.sub\ndef g():\n    return app.sub.leaf.f()\n",
        }
    )
    assert _resolved_targets(root, "app.core") == ["app.sub.leaf"]


def test_namespace_used_by_itself_keeps_the_edge(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/types/models.py": "",
            "app/core.py": "import app.types\ndef f(x):\n    return x(app.types)\n",
        }
    )
    assert _resolved_targets(root, "app.core") == ["app.types"]


def test_aliased_submodule_import_expands_from_the_alias(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/types/models.py": "class Model: ...\n",
            "app/core.py": "import app.types as t\ndef f():\n    return t.models.Model()\n",
        }
    )
    assert _resolved_targets(root, "app.core") == ["app.types.models"]


def test_name_bound_to_two_objects_is_not_analyzed(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/types/models.py": "",
            "other/__init__.py": "",
            "app/core.py": "import app.types\nfrom other import app\n"
            "def f():\n    return app.types.models\n",
        }
    )
    assert "app.types" in _resolved_targets(root, "app.core")


def test_chain_crosses_nested_namespaces(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/ship/rates/table.py": "RATE = 1\n",
            "app/core.py": "import app.ship\ndef f():\n    return app.ship.rates.table.RATE\n",
        }
    )
    assert _resolved_targets(root, "app.core") == ["app.ship.rates.table"]


def test_names_read_through_nested_namespaces_are_found(make_project: MakeProject) -> None:
    from unskein.parsers.usage import collect_names_read_from

    root = make_project(
        {
            "app/__init__.py": "",
            "app/ship/rates/table.py": "RATE = 1\nOTHER = 2\n",
            "app/core.py": "import app.ship\ndef f():\n    return app.ship.rates.table.RATE\n",
        }
    )
    found = collect_names_read_from(
        _parse(root), {"app.ship.rates.table": ["RATE", "OTHER"]}, encoding=None
    )
    assert found == {"app.ship.rates.table": frozenset({"RATE"})}
