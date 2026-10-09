from collections.abc import Callable
from pathlib import Path

from unskein.config import AnalysisConfig, FindingsConfig
from unskein.graph.findings import FindingKind
from unskein.graph.metrics import analyze
from unskein.parsers.python_parser import PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]
FIXTURE = Path(__file__).parent.parent / "fixtures" / "namespace_project"


def _missing(root: Path, config: FindingsConfig | None = None) -> list:
    """Return the rule 10 findings of a project."""
    adapter = PythonAdapter(AnalysisConfig())
    parsed = adapter.resolve_indirection(adapter.parse(sorted(root.rglob("*.py")), root))
    return [f for f in analyze(parsed, config).findings if f.kind is FindingKind.MISSING_MODULE]


def test_lazy_import_of_a_missing_module_is_a_finding() -> None:
    (finding,) = _missing(FIXTURE)
    assert finding.modules == ("app.helpers.gone",)
    assert (finding.evidence["required"], finding.evidence["lazy"]) == (0, 1)
    assert finding.evidence["first"] == "app/core.py:14"
    assert finding.evidence["importers"] == "app.core"
    assert finding.evidence["closest"] == "app"
    assert finding.evidence["symbols"] == "helper"
    assert finding.evidence["fix"] == "restore_or_remove"


def test_type_checking_and_guarded_missing_imports_are_not_findings(
    make_project: MakeProject,
) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/a.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
            "    import app.gone\ntry:\n    import app.other\nexcept ImportError:\n    pass\n",
        }
    )
    assert _missing(root) == []


def test_unpackaged_sources_are_not_findings(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "app"\n',
            "app/__init__.py": "",
            "tests/test_a.py": "import app.gone\n",
        }
    )
    assert _missing(root) == []


def test_symbol_defined_elsewhere_gives_import_from(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/real.py": "def helper(): ...\n",
            "app/other.py": "def helper(): ...\n",
            "app/a.py": "from app.gone import helper\n",
        }
    )
    (finding,) = _missing(root)
    assert finding.evidence["fix"] == "import_from"
    assert finding.evidence["defined_in"] == "app.other"
    assert finding.evidence["also_defined"] == 1
    assert finding.evidence["required"] == 1


def test_a_binding_that_comes_from_the_missing_import_is_not_a_definition(
    make_project: MakeProject,
) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/a.py": "from app.gone import helper\n",
            "app/b.py": "from app.gone import helper\n",
        }
    )
    (finding,) = _missing(root)
    assert finding.evidence["fix"] == "restore_or_remove"
    assert finding.evidence["importers"] == "app.a, app.b"


def test_disabled_findings_hide_rule_10() -> None:
    assert _missing(FIXTURE, FindingsConfig(enabled=False)) == []


def test_stubs_and_compiled_extensions_are_not_missing(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/a.py": "def f():\n    from app._native import Handle\n    return Handle\n",
            "app/_native.pyi": "class Handle: ...\n",
            "app/b.py": "def g():\n    from app.fast import go\n    return go\n",
            "app/fast.cpython-312-x86_64-linux-gnu.so": "",
        }
    )
    assert _missing(root) == []


def test_names_bound_by_imports_are_not_definitions(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/alias.py": "from json import JSONDecoder as Tokenizer\n",
            "app/a.py": "def f():\n    from app.gone import Tokenizer\n    return Tokenizer\n",
        }
    )
    (finding,) = _missing(root)
    assert finding.evidence["fix"] == "restore_or_remove"
