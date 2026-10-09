from collections.abc import Callable
from pathlib import Path

from unskein.parsers.models import WarningCode
from unskein.parsers.requirements import normalize_name, read_dependencies, requirement_name

MakeProject = Callable[[dict[str, str]], Path]


def _read(root: Path):
    """Read the declared dependencies of the distribution at root."""
    warnings: list = []
    return read_dependencies(root, warnings), warnings


def test_names_are_normalized_like_pep_503() -> None:
    assert normalize_name("Litellm_Enterprise") == "litellm-enterprise"
    assert normalize_name("a.b__c") == "a-b-c"


def test_requirement_name_drops_versions_markers_and_extras() -> None:
    assert requirement_name("litellm-enterprise==0.1.73") == "litellm-enterprise"
    assert requirement_name("Pkg[extra]>=1; python_version<'3.10'") == "pkg"
    assert requirement_name("name @ https://example.com/x.whl") == "name"
    assert requirement_name("  ") is None
    assert requirement_name("==1.0") is None


def test_project_dependencies_extras_and_version(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "core"\nversion = "1.2.0"\n'
            'dependencies = ["Requests>=2", "core-utils"]\n'
            '[project.optional-dependencies]\nproxy = ["core-enterprise==0.1"]\n'
        }
    )
    declared, warnings = _read(root)
    assert declared.requires == frozenset({"requests", "core-utils"})
    assert declared.optional == {"proxy": frozenset({"core-enterprise"})}
    assert declared.version == "1.2.0"
    assert declared.manifest == root / "pyproject.toml"
    assert warnings == []


def test_project_without_dependencies_declares_nothing(make_project: MakeProject) -> None:
    root = make_project(
        {"pyproject.toml": '[project]\nname = "core-enterprise"\nversion = "0.1.73"\n'}
    )
    declared, _ = _read(root)
    assert declared.requires == frozenset()


def test_dynamic_dependencies_and_version_are_unknown(make_project: MakeProject) -> None:
    root = make_project(
        {"pyproject.toml": '[project]\nname = "x"\ndynamic = ["dependencies", "version"]\n'}
    )
    declared, _ = _read(root)
    assert declared.requires is None
    assert declared.version is None


def test_dependency_groups_with_includes(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "x"\n[dependency-groups]\n'
            'test = ["pytest", {include-group = "lint"}]\nlint = ["ruff"]\n'
            'loop = [{include-group = "loop"}]\nbad = [{include-group = "missing"}]\n'
        }
    )
    declared, warnings = _read(root)
    assert declared.optional["test"] == frozenset({"pytest", "ruff"})
    assert declared.optional["lint"] == frozenset({"ruff"})
    assert declared.optional["loop"] == frozenset()
    assert declared.optional["bad"] == frozenset()
    assert sorted(w.detail for w in warnings) == ["loop", "missing"]
    assert {w.code for w in warnings} == {WarningCode.INVALID_REQUIREMENT}


def test_invalid_requirement_warns_and_is_skipped(make_project: MakeProject) -> None:
    root = make_project({"pyproject.toml": '[project]\nname = "x"\ndependencies = ["==1", "ok"]\n'})
    declared, warnings = _read(root)
    assert declared.requires == frozenset({"ok"})
    assert [(w.code, w.detail) for w in warnings] == [(WarningCode.INVALID_REQUIREMENT, "==1")]


def test_setup_cfg_install_requires_and_extras(make_project: MakeProject) -> None:
    root = make_project(
        {
            "setup.cfg": "[metadata]\nname = legacy\nversion = 2.0\n"
            "[options]\ninstall_requires =\n    core>=1\n    # comment\n"
            "[options.extras_require]\nfast =\n    core-native\n"
        }
    )
    declared, _ = _read(root)
    assert declared.requires == frozenset({"core"})
    assert declared.optional == {"fast": frozenset({"core-native"})}
    assert declared.version == "2.0"
    assert declared.manifest == root / "setup.cfg"


def test_setup_py_only_is_unknown(make_project: MakeProject) -> None:
    root = make_project({"setup.py": "raise SystemExit('never run')\n"})
    declared, _ = _read(root)
    assert declared.requires is None
    assert declared.manifest is None


def test_unreadable_pyproject_is_quietly_unknown(make_project: MakeProject) -> None:
    root = make_project({"pyproject.toml": "broken = ["})
    declared, warnings = _read(root)
    assert declared.requires is None
    assert warnings == []  # the layout already warns MANIFEST_UNREADABLE


def test_setup_cfg_attr_and_file_versions_are_dynamic(make_project: MakeProject) -> None:
    root = make_project(
        {
            "setup.cfg": "[metadata]\nname = alpha\nversion = attr: apkg.__version__\n"
            "[options]\ninstall_requires =\n    core\n"
        }
    )
    declared, _ = _read(root)
    assert declared.version is None


def test_malformed_dynamic_entries_are_ignored(make_project: MakeProject) -> None:
    root = make_project(
        {"pyproject.toml": '[project]\nname = "x"\ndynamic = [{a = 1}, "dependencies"]\n'}
    )
    declared, _ = _read(root)
    assert declared.requires is None
