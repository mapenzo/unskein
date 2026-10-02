from pathlib import Path

import networkx as nx

from unskein.config import AnalysisConfig, FindingsConfig
from unskein.graph.findings import FindingKind
from unskein.graph.metrics import analyze
from unskein.graph.scripts import ScriptGroup, count_consumers, find_scripts, group_scripts
from unskein.parsers.python_parser import PythonAdapter

ROOT = Path(__file__).parent.parent / "fixtures" / "scripts_project"


def _analyzed(config: FindingsConfig | None = None):
    """Parse, resolve and analyze the scripts fixture."""
    adapter = PythonAdapter(AnalysisConfig())
    parsed = adapter.resolve_indirection(adapter.parse(sorted(ROOT.rglob("*.py")), ROOT))
    return analyze(parsed, config)


def test_unpackaged_modules_nobody_imports_are_scripts() -> None:
    graph = nx.DiGraph([("tools.run", "tools.helper"), ("cookbook.demo", "lib.api")])
    graph.add_node("lib.loose")
    scripts = find_scripts(graph, {"tools.run", "tools.helper", "cookbook.demo"})
    assert scripts == frozenset({"tools.run", "cookbook.demo"})


def test_path_named_files_are_always_scripts() -> None:
    graph = nx.DiGraph([(".github/e2e-stack/check.py", "lib.api")])
    assert find_scripts(graph, {".github/e2e-stack/check.py"}) == frozenset(
        {".github/e2e-stack/check.py"}
    )


def test_consumers_count_distinct_scripts() -> None:
    graph = nx.DiGraph([("a.s1", "lib.x"), ("a.s2", "lib.x"), ("lib.y", "lib.x")])
    assert count_consumers(graph, {"a.s1", "a.s2"}) == {"lib.x": 2}


def test_scripts_are_grouped_by_first_directory() -> None:
    graph = nx.DiGraph(
        [
            ("cookbook.demo", "lib.api"),
            ("cookbook.other", "lib.core"),
            (".github/e2e-stack/check.py", "lib.api"),
        ]
    )
    groups = group_scripts(graph, {"cookbook.demo", "cookbook.other", ".github/e2e-stack/check.py"})
    assert groups == [ScriptGroup("cookbook", 2, ("lib",)), ScriptGroup(".github", 1, ("lib",))]


def test_scripts_leave_ca_metrics_and_orphans() -> None:
    result = _analyzed()
    assert result.scripts == frozenset(
        {"cookbook.demo", "cookbook.other", ".github/e2e-stack/check.py", "tools.run"}
    )
    assert "cookbook.demo" not in result.graph
    assert result.coupling_metrics["lib.api"].afferent == 0
    assert result.coupling_metrics["lib.api"].consumers == 2
    orphans = {f.modules[0] for f in result.findings if f.kind is FindingKind.ORPHAN}
    assert orphans == {"lib.loose"}


def test_tools_helper_imported_only_by_a_script_is_still_a_module() -> None:
    result = _analyzed()
    assert "tools.helper" in result.graph
    assert result.coupling_metrics["tools.helper"].afferent == 0
    assert result.coupling_metrics["tools.helper"].consumers == 1
    orphans = {f.modules[0] for f in result.findings if f.kind is FindingKind.ORPHAN}
    assert "tools.helper" not in orphans


def test_layer_rule_still_evaluates_scripts() -> None:
    # Layers are listed highest first; importing a higher layer from a lower one violates.
    result = _analyzed(FindingsConfig(layers=("cookbook", "lib.api")))
    violations = [f.modules for f in result.findings if f.kind is FindingKind.LAYER_VIOLATION]
    assert ("cookbook.demo", "lib.api") not in violations
    result = _analyzed(FindingsConfig(layers=("lib.api", "cookbook")))
    violations = [f.modules for f in result.findings if f.kind is FindingKind.LAYER_VIOLATION]
    assert ("cookbook.demo", "lib.api") in violations


def test_script_entry_points_come_before_configured_ones() -> None:
    adapter = PythonAdapter(AnalysisConfig())
    parsed = adapter.resolve_indirection(adapter.parse(sorted(ROOT.rglob("*.py")), ROOT))
    parsed.entry_points = ("lib.core",)
    result = analyze(parsed, FindingsConfig(entry_points=("lib.loose",)))
    orphans = {f.modules[0] for f in result.findings if f.kind is FindingKind.ORPHAN}
    assert "lib.loose" not in orphans
