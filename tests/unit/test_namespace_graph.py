from pathlib import Path

from unskein.config import AnalysisConfig, FindingsConfig
from unskein.graph.findings import FindingKind
from unskein.graph.metrics import analyze
from unskein.parsers.python_parser import PythonAdapter

FIXTURE = Path(__file__).parent.parent / "fixtures" / "namespace_project"


def _analyzed(root: Path = FIXTURE, config: FindingsConfig | None = None):
    """Parse, resolve and analyze a project."""
    adapter = PythonAdapter(AnalysisConfig())
    parsed = adapter.resolve_indirection(adapter.parse(sorted(root.rglob("*.py")), root))
    return analyze(parsed, config)


def test_imported_namespaces_are_marked_nodes() -> None:
    result = _analyzed()
    assert result.namespaces == frozenset({"app.types"})
    assert result.graph.nodes["app.types"]["virtual"] == "namespace"
    assert result.virtual == {"app.types": "namespace"}
    assert "app.types.llms" not in result.graph


def test_namespace_metrics_have_no_efferent_coupling() -> None:
    metrics = _analyzed().coupling_metrics["app.types"]
    assert (metrics.afferent, metrics.efferent) == (1, 0)


def test_namespaces_are_not_findings() -> None:
    result = _analyzed()
    assert all("app.types" not in finding.modules for finding in result.findings)


def test_namespace_is_a_layer_violation_target(tmp_path: Path) -> None:
    files = {
        "app/__init__.py": "",
        "app/ui/view.py": "",
        "app/db/store.py": "import app.ui\ndef f(x):\n    return x(app.ui)\n",
    }
    for relative, content in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(content)
    config = FindingsConfig(layers=("app.ui", "app.db"))
    (finding,) = [
        f for f in _analyzed(tmp_path, config).findings if f.kind is FindingKind.LAYER_VIOLATION
    ]
    assert finding.modules == ("app.db.store", "app.ui")


def test_namespace_belongs_to_its_package_without_counting_as_a_module() -> None:
    packages = {p.name: p.modules for p in _analyzed().packages}
    assert packages == {"app": 4, "app.types": 2}


def test_namespace_imported_only_by_scripts_is_not_a_node(tmp_path: Path) -> None:
    files = {
        "pyproject.toml": '[project]\nname = "app"\n[tool.setuptools]\npackages = ["app"]\n',
        "app/__init__.py": "",
        "app/types/models.py": "",
        "tools/run.py": "import app.types\ndef f(x):\n    return x(app.types)\n",
    }
    for relative, content in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(content)
    result = _analyzed(tmp_path)
    assert result.namespaces == frozenset()
    assert "app.types" not in result.graph
