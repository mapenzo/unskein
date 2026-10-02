from collections.abc import Callable
from pathlib import Path

from unskein.parsers.layout import Distribution, detect_distributions
from unskein.parsers.models import WarningCode

MakeProject = Callable[[dict[str, str]], Path]


def _detect(root: Path, configured: list[str] | None = None):
    """Detect the distributions of a project from every .py file under it."""
    return detect_distributions(root, sorted(root.rglob("*.py")), configured)


def _by_root(distributions: tuple[Distribution, ...], root: Path) -> dict[str, Distribution]:
    """Index distributions by their root, relative to the project root."""
    return {d.root.relative_to(root).as_posix(): d for d in distributions}


def test_root_without_manifest_packages_everything(make_project: MakeProject) -> None:
    root = make_project({"app/__init__.py": "", "main.py": ""})
    distributions, warnings = _detect(root)
    assert distributions == (Distribution(root, root, None),)
    assert warnings == []


def test_uv_member_packages_its_normalized_name_only(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "core"\n',
            "core/__init__.py": "",
            "enterprise/pyproject.toml": '[project]\nname = "core-enterprise"\n'
            '[tool.uv.build-backend]\nmodule-root = ""\n',
            "enterprise/core_enterprise/__init__.py": "",
            "enterprise/hooks/__init__.py": "",
        }
    )
    found = _by_root(_detect(root)[0], root)
    assert found["enterprise"].import_root == root / "enterprise"
    assert found["enterprise"].packages == frozenset({"core_enterprise"})
    assert found["."].packages == frozenset({"core"})
    assert list(found) == ["enterprise", "."]


def test_uv_module_name_is_declared_package(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "x"\n'
            '[tool.uv.build-backend]\nmodule-name = "y.z"\n',
            "src/y/__init__.py": "",
        }
    )
    (dist,) = _detect(root)[0]
    assert dist.import_root == root / "src"
    assert dist.packages == frozenset({"y"})


def test_maturin_module_name_and_python_source(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "fast"\n'
            '[tool.maturin]\nmodule-name = "fast._native"\npython-source = "python"\n',
            "python/fast/__init__.py": "",
        }
    )
    (dist,) = _detect(root)[0]
    assert dist.import_root == root / "python"
    assert dist.packages == frozenset({"fast"})


def test_hatch_src_layout_keeps_names(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "pkg"\n'
            '[tool.hatch.build.targets.wheel]\npackages = ["src/pkg"]\n',
            "src/pkg/__init__.py": "",
        }
    )
    (dist,) = _detect(root)[0]
    assert dist.import_root == root / "src"
    assert dist.packages == frozenset({"pkg"})


def test_poetry_packages_with_from(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[tool.poetry]\nname = "p"\n'
            'packages = [{ include = "lib_a", from = "src" }]\n',
            "src/lib_a/__init__.py": "",
        }
    )
    (dist,) = _detect(root)[0]
    assert dist.import_root == root / "src"
    assert dist.packages == frozenset({"lib_a"})


def test_setuptools_packages_and_package_dir(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "s"\n[tool.setuptools]\n'
            'packages = ["one", "one.sub"]\npackage-dir = { "" = "lib" }\n',
            "lib/one/__init__.py": "",
        }
    )
    (dist,) = _detect(root)[0]
    assert dist.import_root == root / "lib"
    assert dist.packages == frozenset({"one"})


def test_setup_cfg_packages_and_package_dir(make_project: MakeProject) -> None:
    root = make_project(
        {
            "setup.cfg": "[options]\npackages =\n    cfgpkg\npackage_dir =\n    =src\n",
            "src/cfgpkg/__init__.py": "",
        }
    )
    (dist,) = _detect(root)[0]
    assert dist.import_root == root / "src"
    assert dist.packages == frozenset({"cfgpkg"})


def test_setup_py_only_uses_the_heuristic_and_is_never_run(make_project: MakeProject) -> None:
    root = make_project(
        {
            "setup.py": "raise SystemExit('setup.py must never be executed')\n",
            "good/__init__.py": "",
            "not-identifier/__init__.py": "",
            "loose/mod.py": "",
        }
    )
    (dist,) = _detect(root)[0]
    assert dist.packages == frozenset({"good"})


def test_invalid_toml_warns_and_uses_the_heuristic(make_project: MakeProject) -> None:
    root = make_project({"pyproject.toml": "not = [valid", "pkg/__init__.py": ""})
    (dist,), warnings = _detect(root)
    assert dist.packages == frozenset({"pkg"})
    assert [w.code for w in warnings] == [WarningCode.MANIFEST_UNREADABLE]
    assert warnings[0].path == root / "pyproject.toml"


def test_wrong_types_in_manifest_fall_back_to_the_heuristic(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": "[project]\nname = 3\n[tool.uv.build-backend]\nmodule-name = 3\n"
            '[tool.hatch.build.targets.wheel]\npackages = "pkg"\n',
            "pkg/__init__.py": "",
        }
    )
    (dist,), warnings = _detect(root)
    assert dist.packages == frozenset({"pkg"})
    assert warnings == []


def test_declared_package_missing_warns_and_is_ignored(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "x"\n'
            '[tool.setuptools]\npackages = ["a", "ghost"]\n',
            "a/__init__.py": "",
        }
    )
    (dist,), warnings = _detect(root)
    assert dist.packages == frozenset({"a"})
    assert [(w.code, w.detail) for w in warnings] == [
        (WarningCode.DECLARED_PACKAGE_MISSING, "ghost")
    ]


def test_configured_source_roots_disable_detection(make_project: MakeProject) -> None:
    root = make_project({"lib/pyproject.toml": '[project]\nname = "z"\n', "lib/z/__init__.py": ""})
    distributions, _ = _detect(root, ["lib"])
    assert distributions == (
        Distribution(root / "lib", root / "lib", None),
        Distribution(root, root, None),
    )


def test_scripts_of_every_distribution_are_read(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "a"\n[project.scripts]\na = "a.cli:main"\n',
            "a/__init__.py": "",
            "b/pyproject.toml": '[project]\nname = "b"\n[project.gui-scripts]\nb = "b.gui"\n',
            "b/b/__init__.py": "",
        }
    )
    found = _by_root(_detect(root)[0], root)
    assert found["."].script_modules == ("a.cli",)
    assert found["b"].script_modules == ("b.gui",)


def test_tool_only_pyproject_ships_everything(make_project: MakeProject) -> None:
    root = make_project(
        {"pyproject.toml": "[tool.ruff]\nline-length = 99\n", "main.py": "", "util.py": ""}
    )
    (dist,), _ = _detect(root)
    assert dist.packages is None


def test_single_module_distribution_ships_its_module(make_project: MakeProject) -> None:
    root = make_project({"pyproject.toml": '[project]\nname = "foo"\n', "foo.py": ""})
    (dist,), _ = _detect(root)
    assert dist.packages == frozenset({"foo"})


def test_setup_cfg_with_percent_does_not_abort(make_project: MakeProject) -> None:
    root = make_project(
        {
            "setup.cfg": "[options]\npackages =\n    pct\npackage_dir =\n    =src%x\n",
            "src%x/pct/__init__.py": "",
        }
    )
    (dist,), warnings = _detect(root)
    assert dist.import_root == root / "src%x"
    assert dist.packages == frozenset({"pct"})
    assert warnings == []
