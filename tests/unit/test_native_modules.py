from collections.abc import Callable
from pathlib import Path

import pathspec

from unskein import pipeline
from unskein.config import AnalysisConfig
from unskein.graph.findings import FindingKind
from unskein.graph.metrics import analyze
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import VirtualKind, VirtualModule, WarningCode
from unskein.parsers.python_parser import PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]
FIXTURE = Path(__file__).parent.parent / "fixtures" / "native_project"


def _parse(root: Path, spec: pathspec.PathSpec | None = None):
    """Discover (evidence files included) and parse a project."""
    adapter = PythonAdapter(AnalysisConfig())
    files = sorted(adapter.discover_files(root, spec or pathspec.PathSpec([])))
    return adapter.parse(files, root)


def _targets(result, module: str) -> list[tuple[str, str | None]]:
    """Return (target, symbol) of the internal imports of one module."""
    (found,) = [m for m in result.modules if m.name == module]
    return [(e.target, e.symbol_name) for e in found.imports if not e.is_external]


def test_fixture_evidence_names_virtual_modules_with_their_kind() -> None:
    virtual = _parse(FIXTURE).virtual
    assert virtual == {
        "pkg._cy": VirtualModule(VirtualKind.COMPILED, True, ("pkg/_cy.pyx",)),
        "pkg._native": VirtualModule(
            VirtualKind.COMPILED, True, ("pkg/_native.pyi", "pyproject.toml:10")
        ),
        "pkg._speed": VirtualModule(
            VirtualKind.COMPILED, True, ("pkg/_speed.cpython-314-x86_64-linux-gnu.so",)
        ),
        "pkg.fast": VirtualModule(VirtualKind.NAMESPACE, True),
        "pkg.fast._impl": VirtualModule(VirtualKind.COMPILED, True, ("pkg/fast/_impl.so",)),
        "pkg.stubonly": VirtualModule(VirtualKind.STUB, True, ("pkg/stubonly.pyi",)),
        "tests": VirtualModule(VirtualKind.NAMESPACE, False),
    }


def test_stub_next_to_its_source_is_ignored() -> None:
    result = _parse(FIXTURE)
    assert "pkg.pure" not in result.virtual
    assert "pkg.pure" in {m.name for m in result.modules}


def test_every_import_form_reaches_the_native_module_without_warnings() -> None:
    result = _parse(FIXTURE)
    assert _targets(result, "pkg.api") == [
        ("pkg._speed", "fast_sum"),
        ("pkg.stubonly", "X"),
        ("pkg.fast._impl", None),
        ("pkg._cy", None),
        ("pkg._native", "Tokenizer"),
    ]
    assert _targets(result, "pkg.loader") == [("pkg._native", None)]
    assert [w for w in result.warnings if w.code is WarningCode.UNRESOLVED_IMPORT] == []


def test_maturin_module_gets_its_distribution() -> None:
    assert _parse(FIXTURE).module_distributions["pkg._native"] == "native-demo"


def test_binary_names_keep_the_text_before_the_first_dot(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/a.abi3.so": "",
            "app/b.cp312-win_amd64.pyd": "",
            "app/c.so": "",
            "app/sub/__init__.pyi": "",
        }
    )
    virtual = _parse(root).virtual
    assert {name: v.kind for name, v in virtual.items()} == {
        "app.a": VirtualKind.COMPILED,
        "app.b": VirtualKind.COMPILED,
        "app.c": VirtualKind.COMPILED,
        "app.sub": VirtualKind.STUB,
    }


def test_evidence_outside_the_project_packages_is_ignored(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "x"\n[tool.maturin]\nmodule-name = "other._x"\n',
            "app/__init__.py": "",
            "_speed.so": "",
        }
    )
    assert _parse(root).virtual == {}


def test_malformed_maturin_module_name_warns(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "x"\n[tool.maturin]\nmodule-name = "app..x"\n',
            "app/__init__.py": "",
        }
    )
    result = _parse(root)
    assert result.virtual == {}
    assert [(w.code, w.detail) for w in result.warnings] == [
        (WarningCode.INVALID_MODULE_NAME, "app..x")
    ]


def test_excluded_evidence_does_not_count(make_project: MakeProject) -> None:
    root = make_project({"app/__init__.py": "", "app/_native.pyi": ""})
    spec = pathspec.GitIgnoreSpec.from_lines(["*.pyi"])
    assert _parse(root, spec).virtual == {}


def test_reexport_through_the_facade_lands_on_the_native_module(
    make_project: MakeProject,
) -> None:
    root = make_project(
        {
            "app/__init__.py": "from app._native import Tokenizer\n",
            "app/_native.pyi": "class Tokenizer: ...\n",
            "app/user.py": "from app import Tokenizer\n",
        }
    )
    resolved = resolve_indirection(_parse(root))
    assert _targets(resolved, "app.user") == [("app._native", "Tokenizer")]
    assert resolved.warnings == []


def test_parallel_parsing_finds_the_same_native_modules() -> None:
    adapter = PythonAdapter(AnalysisConfig())
    files = sorted(adapter.discover_files(FIXTURE, pathspec.PathSpec([])))
    parallel = pipeline.parse_all(files, adapter, FIXTURE, AnalysisConfig(parallel_threshold=1))
    sequential = _parse(FIXTURE)
    assert parallel.virtual == sequential.virtual
    assert _targets(parallel, "pkg.api") == _targets(sequential, "pkg.api")


def test_native_nodes_are_marked_and_left_out_of_module_findings() -> None:
    result = analyze(resolve_indirection(_parse(FIXTURE)))
    assert result.virtual == {
        "pkg._cy": VirtualKind.COMPILED,
        "pkg._native": VirtualKind.COMPILED,
        "pkg._speed": VirtualKind.COMPILED,
        "pkg.fast._impl": VirtualKind.COMPILED,
        "pkg.stubonly": VirtualKind.STUB,
    }
    assert result.coupling_metrics["pkg._native"].afferent == 3
    natives = set(result.virtual)
    module_rules = {
        FindingKind.UNSTABLE_DEPENDENCY,
        FindingKind.BOTTLENECK,
        FindingKind.ORCHESTRATOR,
        FindingKind.ORPHAN,
    }
    assert all(not natives & set(f.modules) for f in result.findings if f.kind in module_rules)


def test_native_modules_count_in_their_parent_package(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/core/__init__.py": "",
            "app/core/_native.pyi": "",
            "app/core/a.py": "from app.core import _native\n",
            "app/web/__init__.py": "",
            "app/web/v.py": "from app.core import _native\n",
        }
    )
    result = analyze(resolve_indirection(_parse(root)))
    core = next(p for p in result.packages if p.name == "app.core")
    assert core.modules == 3


def test_maturin_line_is_the_one_in_its_table(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": (
                '[project]\nname = "x"\n\n[tool.other]\nmodule-name = "nope"\n\n'
                '[tool.maturin]\nmodule-name = "app._native"\n'
            ),
            "app/__init__.py": "",
        }
    )
    assert _parse(root).virtual["app._native"].evidence == ("pyproject.toml:8",)


def test_dangling_symlink_is_no_evidence(make_project: MakeProject) -> None:
    root = make_project({"app/__init__.py": ""})
    (root / "app" / "_gone.so").symlink_to(root / "missing.so")
    assert _parse(root).virtual == {}


def test_index_stays_hashable() -> None:
    adapter = PythonAdapter(AnalysisConfig())
    files = sorted(adapter.discover_files(FIXTURE, pathspec.PathSpec([])))
    assert isinstance(hash(adapter.plan_parse(files, FIXTURE).shared), int)


def test_evidence_files_do_not_count_towards_parallel_parsing(monkeypatch) -> None:
    adapter = PythonAdapter(AnalysisConfig())
    files = sorted(adapter.discover_files(FIXTURE, pathspec.PathSpec([])))
    sources = sum(1 for path in files if path.suffix == ".py")

    def refuse(*args):
        raise AssertionError("parsed in parallel")

    monkeypatch.setattr(pipeline, "_parse_parallel", refuse)
    pipeline.parse_all(files, adapter, FIXTURE, AnalysisConfig(parallel_threshold=sources + 1))
