from collections.abc import Callable
from pathlib import Path

import pathspec

from unskein.config import AnalysisConfig, FindingsConfig
from unskein.graph.findings import FindingKind
from unskein.graph.metrics import AnalysisResult, analyze
from unskein.graph.native import NativeModule
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import VirtualKind
from unskein.parsers.python_parser import PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]
FIXTURE = Path(__file__).parent.parent / "fixtures" / "native_project"
GUARDED_LOADER = (
    "def load():\n    try:\n        from app import _native\n"
    "    except ImportError:\n        return None\n    return _native\n"
)


def _analyzed(root: Path, config: FindingsConfig | None = None) -> AnalysisResult:
    """Discover, parse, resolve and analyze a project."""
    adapter = PythonAdapter(AnalysisConfig())
    files = sorted(adapter.discover_files(root, pathspec.PathSpec([])))
    return analyze(resolve_indirection(adapter.parse(files, root)), config)


def _rule_11(result: AnalysisResult) -> list:
    """Return the rule 11 findings."""
    return [f for f in result.findings if f.kind is FindingKind.OPTIONAL_NATIVE_REQUIRED]


def test_boundary_tallies_uses_of_each_native_module() -> None:
    by_name = {native.name: native for native in _analyzed(FIXTURE).native}
    assert sorted(by_name) == [
        "pkg._cy",
        "pkg._native",
        "pkg._speed",
        "pkg.fast._impl",
        "pkg.stubonly",
    ]
    assert by_name["pkg._native"] == NativeModule(
        name="pkg._native",
        kind=VirtualKind.COMPILED,
        evidence=("pkg/_native.pyi", "pyproject.toml:10"),
        afferent=3,
        required=0,
        lazy=1,
        guarded=1,
        type_only=1,
        unguarded=("pkg/api.py:8",),
        first_guarded="pkg/loader.py:3",
    )
    assert not by_name["pkg._native"].works_without
    assert by_name["pkg._speed"].required == 1


def test_guarded_and_unguarded_uses_make_rule_11() -> None:
    (finding,) = _rule_11(_analyzed(FIXTURE))
    assert finding.modules == ("pkg._native",)
    assert finding.evidence == {
        "kind": "compiled",
        "guarded": 1,
        "first_guarded": "pkg/loader.py:3",
        "required": 0,
        "lazy": 1,
        "unguarded": "pkg/api.py:8",
        "unguarded_total": 1,
        "fix": "guard_or_drop_fallback",
    }


def test_required_everywhere_is_coherent_and_no_finding(make_project: MakeProject) -> None:
    root = make_project(
        {"app/__init__.py": "", "app/_native.pyi": "", "app/a.py": "from app import _native\n"}
    )
    result = _analyzed(root)
    assert _rule_11(result) == []
    (native,) = result.native
    assert (native.required, native.works_without) == (1, False)


def test_guarded_only_works_without_the_extension(make_project: MakeProject) -> None:
    root = make_project(
        {"app/__init__.py": "", "app/_native.pyi": "", "app/loader.py": GUARDED_LOADER}
    )
    result = _analyzed(root)
    (native,) = result.native
    assert native.works_without
    assert _rule_11(result) == []


def test_a_guarded_use_in_tests_does_not_count(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "x"\n[tool.setuptools]\npackages = ["app"]\n',
            "app/__init__.py": "",
            "app/_native.pyi": "",
            "app/a.py": "def f():\n    from app import _native\n    return _native\n",
            "tests/test_loader.py": GUARDED_LOADER,
        }
    )
    assert _rule_11(_analyzed(root)) == []


def test_native_imported_only_by_scripts_is_hidden_with_no_uses(
    make_project: MakeProject,
) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "x"\n[tool.setuptools]\npackages = ["app"]\n',
            "app/__init__.py": "",
            "app/_native.pyi": "",
            "tests/test_it.py": "from app import _native\n",
        }
    )
    result = _analyzed(root)
    assert "app._native" not in result.graph
    (native,) = result.native
    assert (native.afferent, native.required, native.lazy, native.guarded) == (0, 0, 0, 0)
    assert _rule_11(result) == []


def test_disabled_findings_hide_rule_11_but_keep_the_boundary() -> None:
    result = _analyzed(FIXTURE, FindingsConfig(enabled=False))
    assert _rule_11(result) == []
    assert len(result.native) == 5


def test_unguarded_locations_are_capped_in_the_evidence(make_project: MakeProject) -> None:
    files = {"app/__init__.py": "", "app/_native.pyi": "", "app/loader.py": GUARDED_LOADER}
    for number in range(7):
        files[f"app/m{number}.py"] = "def f():\n    from app import _native\n    return _native\n"
    (finding,) = _rule_11(_analyzed(make_project(files)))
    assert finding.evidence["unguarded_total"] == 7
    assert finding.evidence["unguarded"] == (
        "app/m0.py:2, app/m1.py:2, app/m2.py:2, app/m3.py:2, app/m4.py:2"
    )


def test_a_guarded_fallback_in_the_facade_keeps_its_users_guarded(
    make_project: MakeProject,
) -> None:
    root = make_project(
        {
            "pkg/__init__.py": (
                "try:\n    from pkg._speedups import escape\n"
                "except ImportError:\n    from pkg._pure import escape\n"
            ),
            "pkg/_speedups.cpython-312-x86_64-linux-gnu.so": "",
            "pkg/_pure.py": "def escape(text):\n    return text\n",
            "pkg/api.py": "from pkg import escape\n",
            "pkg/api2.py": "import pkg\n\n\ndef f():\n    return pkg.escape('x')\n",
        }
    )
    result = _analyzed(root)
    (native,) = result.native
    assert (native.name, native.guarded, native.unguarded) == ("pkg._speedups", 3, ())
    assert native.works_without
    assert _rule_11(result) == []
