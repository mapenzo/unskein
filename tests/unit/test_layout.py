from collections.abc import Callable
from pathlib import Path

from unskein.parsers.layout import (
    Distribution,
    ModuleName,
    build_layout,
    detect_distributions,
    name_files,
)
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


def _names(root: Path, configured: list[str] | None = None) -> dict[str, ModuleName]:
    """Name every .py file of a project, keyed by its path relative to the root."""
    files = sorted(root.rglob("*.py"))
    layout, _ = build_layout(root, files, configured)
    named, _ = name_files(layout, files)
    return {path.relative_to(root).as_posix(): name for path, name in named}


def _litellm_like(make_project: MakeProject) -> Path:
    """Write a small monorepo shaped like litellm: root package, uv member, legacy dir."""
    return make_project(
        {
            "pyproject.toml": '[project]\nname = "core"\n'
            '[tool.maturin]\nmodule-name = "core._native"\n',
            "core/__init__.py": "",
            "core/main.py": "",
            "enterprise/pyproject.toml": '[project]\nname = "core-enterprise"\n'
            '[tool.uv.build-backend]\nmodule-root = ""\n',
            "enterprise/__init__.py": "",
            "enterprise/core_enterprise/__init__.py": "",
            "enterprise/core_enterprise/proxy.py": "",
            "enterprise/hooks/__init__.py": "",
            "enterprise/hooks/banned.py": "",
            ".circleci/scripts/run.py": "",
            "cookbook/demo.py": "",
            "tool-x/thing.py": "",
        }
    )


def test_files_take_the_name_of_the_distribution_that_ships_them(make_project: MakeProject) -> None:
    names = _names(_litellm_like(make_project))
    assert names["core/main.py"] == ModuleName("core.main", True, "core")
    assert names["enterprise/core_enterprise/proxy.py"] == ModuleName(
        "core_enterprise.proxy", True, "core-enterprise"
    )
    assert names["enterprise/hooks/banned.py"] == ModuleName("enterprise.hooks.banned", False)
    assert names["cookbook/demo.py"] == ModuleName("cookbook.demo", False)


def test_member_init_outside_its_packages_falls_back_to_the_root(make_project: MakeProject) -> None:
    names = _names(_litellm_like(make_project))
    assert names["enterprise/__init__.py"] == ModuleName("enterprise", False)


def test_non_identifier_paths_are_named_by_path(make_project: MakeProject) -> None:
    names = _names(_litellm_like(make_project))
    assert names[".circleci/scripts/run.py"] == ModuleName(".circleci/scripts/run.py", False)
    assert names["tool-x/thing.py"] == ModuleName("tool-x/thing.py", False)


def test_root_without_manifest_names_as_before(make_project: MakeProject) -> None:
    root = make_project(
        {"app/__init__.py": "", "app/core.py": "", "main.py": "", "src/lib/x.py": ""}
    )
    names = _names(root)
    assert names["app/core.py"] == ModuleName("app.core", True)
    assert names["main.py"] == ModuleName("main", True)
    assert names["src/lib/x.py"] == ModuleName("lib.x", True)


def test_configured_roots_name_as_before(make_project: MakeProject) -> None:
    root = make_project({"lib/pkg/__init__.py": "", "lib/pkg/a.py": "", "tool.py": ""})
    names = _names(root, ["lib"])
    assert names["lib/pkg/a.py"] == ModuleName("pkg.a", True)
    assert names["tool.py"] == ModuleName("tool", True)


def test_collision_keeps_the_deepest_and_names_the_other_by_path(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "x"\n[tool.setuptools]\npackages = ["shared"]\n',
            "shared/__init__.py": "",
            "member/pyproject.toml": '[project]\nname = "shared"\n',
            "member/shared/__init__.py": "",
        }
    )
    files = sorted(root.rglob("*.py"))
    layout, _ = build_layout(root, files, None)
    named, warnings = name_files(layout, files)
    by_path = {p.relative_to(root).as_posix(): n for p, n in named}
    assert by_path["member/shared/__init__.py"] == ModuleName("shared", True, "shared")
    assert by_path["shared/__init__.py"] == ModuleName("shared/__init__.py", False)
    assert [(w.code, w.path) for w in warnings] == [
        (WarningCode.MODULE_NAME_COLLISION, root / "shared/__init__.py")
    ]


def test_layout_keeps_symlinked_link_paths(make_project: MakeProject, tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    (outside / "linked").mkdir(parents=True)
    (outside / "linked" / "__init__.py").write_text("")
    root = make_project({"app/__init__.py": ""})
    (root / "linked").symlink_to(outside / "linked", target_is_directory=True)
    files = [root / "app/__init__.py", root / "linked/__init__.py"]
    layout, _ = build_layout(root, files, None)
    named, _ = name_files(layout, files)
    assert [n.name for _, n in named] == ["app", "linked"]


def test_layout_exposes_the_scripts_of_every_distribution(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "a"\n[project.scripts]\na = "a.cli:main"\n',
            "a/__init__.py": "",
            "b/pyproject.toml": '[project]\nname = "b"\n[project.scripts]\nb = "b.run"\n',
            "b/b/__init__.py": "",
        }
    )
    layout, _ = build_layout(root, sorted(root.rglob("*.py")), None)
    assert layout.script_modules == ("a.cli", "b.run")


def test_uv_empty_module_root_without_module_name_is_kept(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "pkg"\n'
            '[tool.uv.build-backend]\nmodule-root = ""\n',
            "pkg/__init__.py": "",
            "pkg/a.py": "",
            "src/other/__init__.py": "",
        }
    )
    distributions, _ = _detect(root)
    assert distributions[-1].import_root == root
    assert distributions[-1].packages == frozenset({"pkg"})
    layout, _ = build_layout(root, sorted(root.rglob("*.py")), None)
    assert layout.name_of(root / "pkg/a.py") == ModuleName("pkg.a", True, "pkg")


FLAT_DIRS = {"mysite/__init__.py": "", "polls/__init__.py": "", "polls/views.py": ""}


def _flat_packages(make_project: MakeProject, pyproject: str) -> frozenset[str] | None:
    """Return the packages detected for a flat project with the given pyproject."""
    root = make_project({"pyproject.toml": pyproject, **FLAT_DIRS})
    distributions, _ = _detect(root)
    return distributions[-1].packages


def test_setuptools_backend_ships_every_regular_package(make_project: MakeProject) -> None:
    pyproject = (
        '[build-system]\nbuild-backend = "setuptools.build_meta"\n[project]\nname = "mysite"\n'
    )
    assert _flat_packages(make_project, pyproject) == frozenset({"mysite", "polls"})


def test_missing_build_system_is_setuptools(make_project: MakeProject) -> None:
    assert _flat_packages(make_project, '[project]\nname = "mysite"\n') == frozenset(
        {"mysite", "polls"}
    )


def test_hatchling_backend_ships_only_the_normalized_name(make_project: MakeProject) -> None:
    pyproject = '[build-system]\nbuild-backend = "hatchling.build"\n[project]\nname = "mysite"\n'
    assert _flat_packages(make_project, pyproject) == frozenset({"mysite"})


def test_equal_depth_collision_keeps_the_smaller_path(make_project: MakeProject) -> None:
    root = make_project(
        {
            "services/a/pyproject.toml": '[project]\nname = "app"\n',
            "services/a/app/__init__.py": "",
            "services/b/pyproject.toml": '[project]\nname = "app"\n',
            "services/b/app/__init__.py": "",
        }
    )
    files = sorted(root.rglob("*.py"))
    layout, _ = build_layout(root, files, None)
    named, warnings = name_files(layout, files)
    by_path = {p.relative_to(root).as_posix(): n for p, n in named}
    assert by_path["services/a/app/__init__.py"] == ModuleName("app", True, "app")
    assert by_path["services/b/app/__init__.py"] == ModuleName("services/b/app/__init__.py", False)
    assert [w.code for w in warnings] == [WarningCode.MODULE_NAME_COLLISION]


def test_no_manifest_with_src_yields_src_then_root(make_project: MakeProject) -> None:
    root = make_project({"src/app/__init__.py": "", "tool.py": ""})
    distributions, _ = _detect(root)
    assert [(d.import_root, d.packages) for d in distributions] == [
        (root / "src", None),
        (root, None),
    ]


def test_named_distributions_carry_their_declared_dependencies() -> None:
    root = Path(__file__).parent.parent / "fixtures" / "distributions_monorepo"
    layout, _ = build_layout(root, sorted(root.rglob("*.py")), None)
    infos = {info.name: info for info in layout.distribution_infos}
    assert list(infos) == ["core", "core-plugins"]
    assert infos["core"].requires == frozenset({"requests"})
    assert dict(infos["core"].optional) == {"plugins": frozenset({"core-plugins"})}
    assert infos["core"].version == "2.3.0"
    assert infos["core-plugins"].requires == frozenset()
    assert infos["core-plugins"].manifest == root / "plugins" / "pyproject.toml"


def test_module_names_know_their_distribution() -> None:
    root = Path(__file__).parent.parent / "fixtures" / "distributions_monorepo"
    files = sorted(root.rglob("*.py"))
    layout, _ = build_layout(root, files, None)
    named, _ = name_files(layout, files)
    by_name = {name.name: name.distribution for _, name in named}
    assert by_name["core.engine"] == "core"
    assert by_name["core_plugins.extra"] == "core-plugins"
    assert by_name["legacy.tool"] is None


def test_roots_without_manifest_or_name_have_no_distribution(make_project: MakeProject) -> None:
    root = make_project({"app/__init__.py": "", "app/a.py": ""})
    files = sorted(root.rglob("*.py"))
    layout, _ = build_layout(root, files, None)
    named, _ = name_files(layout, files)
    assert layout.distribution_infos == ()
    assert {name.distribution for _, name in named} == {None}


def test_two_manifests_with_one_name_warn_and_only_the_shallower_is_named(
    make_project: MakeProject,
) -> None:
    root = make_project(
        {
            "pyproject.toml": '[project]\nname = "a"\n',
            "a/__init__.py": "",
            "one/pyproject.toml": '[project]\nname = "Twin"\n',
            "one/twin/__init__.py": "",
            "deep/two/pyproject.toml": '[project]\nname = "twin"\n',
            "deep/two/twin_b/__init__.py": "",
        }
    )
    files = sorted(root.rglob("*.py"))
    layout, warnings = build_layout(root, files, None)
    named, _ = name_files(layout, files)
    by_name = {name.name: name.distribution for _, name in named}
    assert by_name["twin"] == "twin"
    assert by_name["twin_b"] is None
    assert [(w.code, w.detail) for w in warnings] == [
        (WarningCode.DUPLICATE_DISTRIBUTION_NAME, "twin")
    ]
    assert warnings[0].path == root / "deep" / "two"


def test_setup_cfg_name_is_read_when_pyproject_declares_packages(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pyproject.toml": '[tool.setuptools]\npackages = ["pkg"]\n',
            "setup.cfg": "[metadata]\nname = Named\n",
            "pkg/__init__.py": "",
        }
    )
    layout, _ = build_layout(root, sorted(root.rglob("*.py")), None)
    assert [info.name for info in layout.distribution_infos] == ["named"]
