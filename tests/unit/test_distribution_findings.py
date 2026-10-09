from collections.abc import Callable
from pathlib import Path

from unskein.config import AnalysisConfig, FindingsConfig
from unskein.graph.distributions import DependencyStatus
from unskein.graph.findings import FindingKind
from unskein.graph.metrics import analyze
from unskein.parsers.python_parser import PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]

FIXTURE = Path(__file__).parent.parent / "fixtures" / "distributions_monorepo"


def _analyzed(root: Path, config: FindingsConfig | None = None):
    """Parse, resolve and analyze a project."""
    adapter = PythonAdapter(AnalysisConfig())
    parsed = adapter.resolve_indirection(adapter.parse(sorted(root.rglob("*.py")), root))
    return analyze(parsed, config)


def _by_kind(result) -> dict[FindingKind, list]:
    """Group the distribution findings of a result by kind."""
    kinds = {
        FindingKind.UNDECLARED_DEPENDENCY,
        FindingKind.OPTIONAL_REQUIRED,
        FindingKind.UNPACKAGED_IMPORT,
        FindingKind.DISTRIBUTION_CYCLE,
    }
    grouped: dict[FindingKind, list] = {}
    for finding in result.findings:
        if finding.kind in kinds:
            grouped.setdefault(finding.kind, []).append(finding)
    return grouped


def test_undeclared_dependency_with_fix() -> None:
    (finding,) = _by_kind(_analyzed(FIXTURE))[FindingKind.UNDECLARED_DEPENDENCY]
    assert finding.modules == ("core-plugins", "core")
    assert finding.evidence["required"] == 2
    assert finding.evidence["first"] == "plugins/core_plugins/__init__.py:1"
    assert finding.evidence["fix"] == "add_dependency"
    assert finding.evidence["manifest"] == "plugins/pyproject.toml"
    assert finding.evidence["table"] == "[project] dependencies"
    assert finding.evidence["requirement"] == '"core>=2.3.0"'


def test_guarded_optional_use_is_not_a_finding() -> None:
    grouped = _by_kind(_analyzed(FIXTURE))
    assert FindingKind.OPTIONAL_REQUIRED not in grouped


def test_unpackaged_lazy_import_is_a_finding() -> None:
    (finding,) = _by_kind(_analyzed(FIXTURE))[FindingKind.UNPACKAGED_IMPORT]
    assert finding.modules == ("core", "legacy")
    assert finding.evidence["lazy"] == 1
    assert finding.evidence["targets"] == "legacy.tool"
    assert finding.evidence["directory"] == "legacy/"
    assert finding.evidence["first"] == "core/legacy_user.py:2"


def test_cycle_between_distributions_with_cut_edge() -> None:
    result = _analyzed(FIXTURE)
    (finding,) = _by_kind(result)[FindingKind.DISTRIBUTION_CYCLE]
    assert finding.modules == ("core", "core-plugins")
    assert finding.evidence["cuts"] == "core → core-plugins"
    assert finding.evidence["cut_breaking"] == 0
    edges = {(e.source, e.target): e for e in result.distribution_edges}
    assert edges["core", "core-plugins"].status is DependencyStatus.OPTIONAL
    assert edges["core", "core-plugins"].extras == ("plugins",)
    assert edges["core", "core-plugins"].counts.guarded == 1
    assert edges["core-plugins", "core"].status is DependencyStatus.UNDECLARED


def test_installability_summary() -> None:
    summaries = {s.name: s for s in _analyzed(FIXTURE).distributions}
    assert summaries["core-plugins"].installable is False
    assert summaries["core-plugins"].blocker == "plugins/core_plugins/__init__.py:1 → core"
    assert summaries["core"].installable is False  # unpackaged legacy/ import
    assert summaries["core"].uses == ("core-plugins",)


def test_optional_used_as_required(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "a"\nversion = "1"\n'
            '[project.optional-dependencies]\nx = ["b"]\n',
            "a/__init__.py": "import b_pkg\n",
            "bdist/pyproject.toml": '[project]\nname = "b"\nversion = "1"\ndependencies = []\n'
            '[tool.uv.build-backend]\nmodule-root = ""\nmodule-name = "b_pkg"\n',
            "bdist/b_pkg/__init__.py": "",
        }
    )
    (finding,) = _by_kind(_analyzed(root))[FindingKind.OPTIONAL_REQUIRED]
    assert finding.modules == ("a", "b")
    assert finding.evidence["extras"] == "x"
    assert finding.evidence["fix"] == "promote_or_guard"


def test_unknown_dependencies_are_never_sources_of_rules_6_and_7(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "a"\ndynamic = ["dependencies"]\n',
            "a/__init__.py": "import b_pkg\n",
            "bdist/pyproject.toml": '[project]\nname = "b"\n'
            '[tool.uv.build-backend]\nmodule-root = ""\nmodule-name = "b_pkg"\n',
            "bdist/b_pkg/__init__.py": "",
        }
    )
    result = _analyzed(root)
    assert FindingKind.UNDECLARED_DEPENDENCY not in _by_kind(result)
    assert {s.name: s.installable for s in result.distributions}["a"] is None


def test_version_missing_gives_bare_requirement(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "a"\ndependencies = []\n',
            "a/__init__.py": "import b_pkg\n",
            "bdist/pyproject.toml": '[project]\nname = "b"\ndynamic = ["version"]\n'
            '[tool.uv.build-backend]\nmodule-root = ""\nmodule-name = "b_pkg"\n',
            "bdist/b_pkg/__init__.py": "",
        }
    )
    (finding,) = _by_kind(_analyzed(root))[FindingKind.UNDECLARED_DEPENDENCY]
    assert finding.evidence["requirement"] == '"b"'


def test_setup_cfg_manifest_uses_install_requires(make_project: MakeProject) -> None:
    root = make_project(
        {
            "setup.cfg": "[metadata]\nname = a\n[options]\ninstall_requires =\n    requests\n",
            "a/__init__.py": "import b_pkg\n",
            "bdist/pyproject.toml": '[project]\nname = "b"\nversion = "3"\n'
            '[tool.uv.build-backend]\nmodule-root = ""\nmodule-name = "b_pkg"\n',
            "bdist/b_pkg/__init__.py": "",
        }
    )
    (finding,) = _by_kind(_analyzed(root))[FindingKind.UNDECLARED_DEPENDENCY]
    assert finding.evidence["table"] == "[options] install_requires"
    assert finding.evidence["manifest"] == "setup.cfg"


def test_imports_inside_one_distribution_are_ignored(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "a"\ndependencies = []\n'
            '[tool.setuptools]\npackages = ["a", "a_extra"]\n',
            "a/__init__.py": "import a_extra\n",
            "a_extra/__init__.py": "import a\n",
        }
    )
    result = _analyzed(root)
    assert result.distribution_edges == []
    assert _by_kind(result) == {}


def test_unparsed_targets_are_skipped(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[build-system]\nbuild-backend = "hatchling.build"\n'
            '[project]\nname = "a"\ndependencies = []\n',
            "a/__init__.py": "import a.broken\nimport legacy.broken\n",
            "a/broken.py": "def (:\n",
            "legacy/__init__.py": "",
            "legacy/broken.py": "def (:\n",
        }
    )
    result = _analyzed(root)
    assert result.distribution_edges == []
    assert FindingKind.UNPACKAGED_IMPORT not in _by_kind(result)


def test_scripts_are_not_sources(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "a"\ndependencies = []\n',
            "a/__init__.py": "",
            "tools/run.py": "import a\nimport legacy\n",
            "legacy/__init__.py": "",
        }
    )
    assert _by_kind(_analyzed(root)) == {}


def test_no_named_distributions_changes_nothing() -> None:
    root = Path(__file__).parent.parent / "fixtures" / "simple_project"
    result = _analyzed(root)
    assert result.distributions == []
    assert result.distribution_edges == []
    assert _by_kind(result) == {}


def test_disabled_findings_keep_the_summary() -> None:
    result = _analyzed(FIXTURE, FindingsConfig(enabled=False))
    assert _by_kind(result) == {}
    assert {s.name: s.installable for s in result.distributions}["core-plugins"] is False


def test_analysis_is_deterministic() -> None:
    first = _analyzed(FIXTURE)
    second = _analyzed(FIXTURE)
    assert first.findings == second.findings
    assert first.distribution_edges == second.distribution_edges


def test_cycle_of_three_lists_every_cut_needed_to_break_it(make_project: MakeProject) -> None:
    uv_member = (
        '[project]\nname = "{name}"\ndependencies = []\n'
        '[tool.uv.build-backend]\nmodule-root = ""\nmodule-name = "{module}"\n'
    )
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "a"\ndependencies = []\n',
            "a/__init__.py": "import b_pkg\nimport b_pkg.x\n",
            "bdist/pyproject.toml": uv_member.format(name="b", module="b_pkg"),
            "bdist/b_pkg/__init__.py": (
                "import a\ntry:\n    import c_pkg\nexcept ImportError:\n    pass\n"
            ),
            "bdist/b_pkg/x.py": "",
            "cdist/pyproject.toml": uv_member.format(name="c", module="c_pkg"),
            "cdist/c_pkg/__init__.py": "import b_pkg\nimport b_pkg.x\nimport b_pkg\n",
        }
    )
    (finding,) = _by_kind(_analyzed(root))[FindingKind.DISTRIBUTION_CYCLE]
    assert finding.modules == ("a", "b", "c")
    assert finding.evidence["cuts"] == "b → c, b → a"
    assert finding.evidence["cut_breaking"] == 1


def test_two_manifests_with_the_same_name_give_one_summary(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "a"\ndependencies = []\n',
            "a/__init__.py": "",
            "one/pyproject.toml": '[project]\nname = "twin"\nversion = "1"\n',
            "one/twin/__init__.py": "",
            "two/pyproject.toml": '[project]\nname = "twin"\nversion = "2"\n',
            "two/twin/__init__.py": "",
        }
    )
    names = [summary.name for summary in _analyzed(root).distributions]
    assert names == ["a", "twin"]


def test_code_shipped_by_an_unnamed_distribution_is_not_unpackaged(
    make_project: MakeProject,
) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "core"\ndependencies = []\n',
            "core/__init__.py": "",
            "core/a.py": "import legacy_pkg.x\n",
            "legacy_member/setup.py": "raise SystemExit('never run')\n",
            "legacy_member/legacy_pkg/__init__.py": "",
            "legacy_member/legacy_pkg/x.py": "",
        }
    )
    assert FindingKind.UNPACKAGED_IMPORT not in _by_kind(_analyzed(root))


def test_unpackaged_fix_names_the_real_directory(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[build-system]\nbuild-backend = "hatchling.build"\n'
            '[project]\nname = "core"\ndependencies = []\n',
            "core/__init__.py": "",
            "core/a.py": "import plug.tools.t\n",
            "plug/pyproject.toml": '[project]\nname = "plug"\n[tool.uv.build-backend]\n'
            'module-root = ""\nmodule-name = "plug_pkg"\n',
            "plug/plug_pkg/__init__.py": "",
            "plug/tools/__init__.py": "",
            "plug/tools/t.py": "",
        }
    )
    (finding,) = _by_kind(_analyzed(root))[FindingKind.UNPACKAGED_IMPORT]
    assert finding.evidence["directory"] == "plug/tools/"


def test_rules_7_and_8_carry_every_use_count(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "a"\nversion = "1"\n'
            '[project.optional-dependencies]\nx = ["b"]\n',
            "a/__init__.py": "try:\n    import b_pkg\nexcept ImportError:\n    pass\n"
            "import b_pkg\ndef f():\n    import b_pkg\n",
            "bdist/pyproject.toml": '[project]\nname = "b"\nversion = "1"\ndependencies = []\n'
            '[tool.uv.build-backend]\nmodule-root = ""\nmodule-name = "b_pkg"\n',
            "bdist/b_pkg/__init__.py": "",
        }
    )
    (finding,) = _by_kind(_analyzed(root))[FindingKind.OPTIONAL_REQUIRED]
    assert (finding.evidence["lazy"], finding.evidence["guarded"]) == (1, 1)
    (fixture_finding,) = _by_kind(_analyzed(FIXTURE))[FindingKind.UNPACKAGED_IMPORT]
    assert fixture_finding.evidence["guarded"] == 0


def test_imports_into_an_unparsed_file_of_another_distribution_count(
    make_project: MakeProject,
) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "a"\ndependencies = []\n',
            "a/__init__.py": "import b_pkg.broken\n",
            "bdist/pyproject.toml": '[project]\nname = "b"\n[tool.uv.build-backend]\n'
            'module-root = ""\nmodule-name = "b_pkg"\n',
            "bdist/b_pkg/__init__.py": "",
            "bdist/b_pkg/broken.py": "def (:\n",
        }
    )
    (finding,) = _by_kind(_analyzed(root))[FindingKind.UNDECLARED_DEPENDENCY]
    assert finding.modules == ("a", "b")


def test_poetry_manifest_gets_a_poetry_fix(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "a"\nversion = "1.5"\ndependencies = []\n',
            "a/__init__.py": "",
            "poet/pyproject.toml": '[tool.poetry]\nname = "p"\nversion = "2"\n'
            'packages = [{include = "p_pkg"}]\n[tool.poetry.dependencies]\npython = "^3.12"\n',
            "poet/p_pkg/__init__.py": "import a\n",
        }
    )
    (finding,) = _by_kind(_analyzed(root))[FindingKind.UNDECLARED_DEPENDENCY]
    assert finding.evidence["table"] == "[tool.poetry.dependencies]"
    assert finding.evidence["requirement"] == 'a = ">=1.5"'
    assert finding.evidence["manifest"] == "poet/pyproject.toml"


def test_distribution_values_are_hashable() -> None:
    result = _analyzed(FIXTURE)
    for edge in result.distribution_edges:
        hash(edge)
    for summary in result.distributions:
        hash(summary)
