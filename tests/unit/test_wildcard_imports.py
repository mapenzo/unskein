from collections.abc import Callable
from pathlib import Path

import pathspec

from unskein.config import AnalysisConfig, FindingsConfig
from unskein.graph.findings import FindingKind
from unskein.graph.metrics import AnalysisResult, analyze
from unskein.graph.stars import WildcardAction, WildcardFix, WildcardReason
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.python_parser import PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]
FIXTURE = Path(__file__).parent.parent / "fixtures" / "star_project"


def _analyzed(root: Path = FIXTURE, config: FindingsConfig | None = None) -> AnalysisResult:
    """Discover, parse, resolve and analyze a project."""
    adapter = PythonAdapter(AnalysisConfig())
    files = sorted(adapter.discover_files(root, pathspec.PathSpec([])))
    return analyze(resolve_indirection(adapter.parse(files, root)), config)


def _by_name(result: AnalysisResult) -> dict:
    """Return the wildcard summaries by module."""
    return {wildcard.name: wildcard for wildcard in result.wildcards}


def test_one_summary_per_star_imported_module_most_importers_first() -> None:
    assert [w.name for w in _analyzed().wildcards] == [
        "app.types",
        "app.models",
        "app.chain_mid",
        "app.listed",
        "app.sub",
    ]


def test_fixes_of_the_types_module() -> None:
    types = _by_name(_analyzed())["app.types"]
    assert (types.importers, types.names, types.used_min, types.used_max, types.unused) == (
        5,
        4,
        0,
        2,
        1,
    )
    assert types.fixes == (
        WildcardFix("app/annot.py:1", "app.annot", WildcardAction.EXPLICIT, ("D",)),
        WildcardFix("app/api.py:1", "app.api", WildcardAction.EXPLICIT, ("A", "B")),
        WildcardFix("app/both.py:1", "app.both", WildcardAction.EXPLICIT, ("A",)),
        WildcardFix(
            "app/chain_mid.py:1",
            "app.chain_mid",
            WildcardAction.EXPLICIT,
            ("C",),
            kept=("C",),
            kept_for=(("app.chain_top", "C"),),
        ),
        WildcardFix("app/dead.py:1", "app.dead", WildcardAction.REMOVE),
    )


def test_every_star_that_brings_a_needed_name_keeps_it_with_notes() -> None:
    models = _by_name(_analyzed())["app.models"]
    both, relay = models.fixes
    assert both == WildcardFix(
        "app/both.py:2",
        "app.both",
        WildcardAction.EXPLICIT,
        ("A", "Model", "json"),
        defined_elsewhere=(("app.types", "A"),),
        external=("json",),
    )
    assert relay == WildcardFix(
        "app/relay.py:1",
        "app.relay",
        WildcardAction.EXPLICIT,
        ("Model",),
        kept=("Model",),
        kept_for=(("app.consumer", "Model"),),
    )
    assert models.reexported == 1


def test_a_chain_imports_from_the_middle_module() -> None:
    (fix,) = _by_name(_analyzed())["app.chain_mid"].fixes
    assert fix == WildcardFix(
        "app/chain_top.py:1",
        "app.chain_top",
        WildcardAction.EXPLICIT,
        ("C",),
        defined_elsewhere=(("app.types", "C"),),
    )


def test_literal_all_limits_the_names_and_a_self_star_is_removed() -> None:
    by_name = _by_name(_analyzed())
    assert by_name["app.listed"].names == 1
    sub = by_name["app.sub"]
    assert sub.is_self
    assert sub.fixes == (
        WildcardFix("app/sub/__init__.py:1", "app.sub", WildcardAction.REMOVE_SELF),
    )


def test_dynamic_external_facade_and_test_stars_have_no_fix() -> None:
    locations = {f.location for w in _analyzed().wildcards for f in w.fixes}
    assert not {"app/uses_dynamic.py:1", "app/ext.py:1", "tests/test_star.py:1"} & locations
    assert "app/__init__.py:1" not in locations


def test_findings_carry_the_summary_and_follow_the_same_order() -> None:
    findings = [f for f in _analyzed().findings if f.kind is FindingKind.WILDCARD_IMPORT]
    assert [f.modules for f in findings][0] == ("app.types",)
    assert findings[0].evidence == {
        "kind": "module",
        "importers": 5,
        "statements": 5,
        "names": 4,
        "used_min": 0,
        "used_max": 2,
        "unused_statements": 1,
        "no_fix_statements": 0,
        "reexported": 1,
        "fixes": (
            "app/annot.py:1 from app.types import D; app/api.py:1 from app.types import A, B; "
            "app/both.py:1 from app.types import A; app/chain_mid.py:1 from app.types import C; "
            "app/dead.py:1 remove"
        ),
        "fixes_total": 5,
    }
    assert findings[-1].evidence["kind"] == "self"


def test_disabled_findings_hide_rule_12() -> None:
    result = _analyzed(config=FindingsConfig(enabled=False))
    assert result.wildcards == []
    assert all(f.kind is not FindingKind.WILDCARD_IMPORT for f in result.findings)


def test_stars_in_a_cycle_get_no_fix_and_warn(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/a.py": "from app.b import *\nX = 1\n",
            "app/b.py": "from app.a import *\nY = 2\n\n\ndef f():\n    return X\n",
        }
    )
    result = _analyzed(root)
    reasons = [(f.location, f.action, f.reason) for w in result.wildcards for f in w.fixes]
    assert sorted(reasons) == [
        ("app/a.py:1", WildcardAction.NO_FIX, WildcardReason.CYCLE),
        ("app/b.py:1", WildcardAction.NO_FIX, WildcardReason.CYCLE),
    ]
    stars = sorted(w.path.name for w in result.parse_warnings if w.code == "star_import")
    assert stars == ["a.py", "b.py"]


def test_a_name_a_test_imports_through_the_module_is_kept(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "x"\n[tool.setuptools]\npackages = ["app"]\n',
            "app/__init__.py": "",
            "app/types.py": "A = 1\n",
            "app/m.py": "from app.types import *\n",
            "tests/test_m.py": "from app.m import A\n",
        }
    )
    (fix,) = _by_name(_analyzed(root))["app.types"].fixes
    assert (fix.names, fix.kept_for) == (("A",), (("tests.test_m", "A"),))
