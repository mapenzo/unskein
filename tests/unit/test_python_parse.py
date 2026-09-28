from collections.abc import Callable
from pathlib import Path

import pathspec

from unskein.config import AnalysisConfig
from unskein.parsers.models import ParseResult
from unskein.parsers.python_parser import PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]
Edge = tuple[str, str, str | None, bool]


def parse(root: Path, config: AnalysisConfig | None = None) -> ParseResult:
    adapter = PythonAdapter(config)
    files = sorted(adapter.discover_files(root, pathspec.PathSpec([])))
    return adapter.parse(files, root)


def edges(result: ParseResult) -> set[Edge]:
    return {
        (e.source, e.target, e.symbol_name, e.is_external)
        for m in result.modules
        for e in m.imports
    }


def internal(result: ParseResult) -> set[Edge]:
    return {e for e in edges(result) if not e[3]}


def test_simple_project_edges(simple_project: Path) -> None:
    result = parse(simple_project)
    assert result.language == "python"
    assert {m.name for m in result.modules} == {
        "app",
        "app.main",
        "app.models",
        "app.services",
        "app.services.user",
    }
    assert edges(result) == {
        ("app.main", "os", None, True),
        ("app.main", "app.services.user", "UserService", False),
        ("app.services.user", "app.models", "User", False),
    }
    assert result.warnings == []


def test_line_numbers_are_recorded(make_project: MakeProject) -> None:
    root = make_project({"app/__init__.py": "", "app/a.py": "\n\nimport app.b\n", "app/b.py": ""})
    [edge] = next(m for m in parse(root).modules if m.name == "app.a").imports
    assert edge.line_number == 3


def test_symbol_import_targets_module_and_submodule_import_targets_submodule(
    make_project: MakeProject,
) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/pkg/__init__.py": "",
            "app/pkg/mod.py": "X = 1\n",
            "app/use.py": "from app.pkg import mod\nfrom app.pkg.mod import X\n",
        }
    )
    assert internal(parse(root)) == {
        ("app.use", "app.pkg.mod", None, False),
        ("app.use", "app.pkg.mod", "X", False),
    }


def test_relative_imports_resolve_from_module_and_package(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "from . import models\n",
            "app/models.py": "",
            "app/sub/__init__.py": "",
            "app/sub/a.py": "from . import b\nfrom ..models import Base\n",
            "app/sub/b.py": "",
        }
    )
    assert internal(parse(root)) == {
        ("app", "app.models", None, False),
        ("app.sub.a", "app.sub.b", None, False),
        ("app.sub.a", "app.models", "Base", False),
    }


def test_relative_import_beyond_top_level_is_warned_and_skipped(make_project: MakeProject) -> None:
    root = make_project({"app/__init__.py": "", "app/a.py": "from ... import nope\n"})
    result = parse(root)
    assert internal(result) == set()
    assert len(result.warnings) == 1
    assert "app/a.py" in result.warnings[0].replace("\\", "/")


def test_star_import_keeps_module_edge_and_warns(make_project: MakeProject) -> None:
    root = make_project(
        {"app/__init__.py": "", "app/a.py": "from app.b import *\n", "app/b.py": ""}
    )
    result = parse(root)
    assert internal(result) == {("app.a", "app.b", None, False)}
    assert len(result.warnings) == 1
    assert "*" in result.warnings[0]


def test_missing_internal_module_falls_back_to_ancestor_with_warning(
    make_project: MakeProject,
) -> None:
    root = make_project({"app/__init__.py": "", "app/a.py": "import app.missing.deep\n"})
    result = parse(root)
    assert internal(result) == {("app.a", "app", None, False)}
    assert len(result.warnings) == 1
    assert "app.missing.deep" in result.warnings[0]


def test_missing_import_in_namespace_package_is_skipped_with_clear_warning(
    make_project: MakeProject,
) -> None:
    root = make_project({"app/a.py": "import app.missing\n"})
    result = parse(root)
    assert internal(result) == set()
    assert len(result.warnings) == 1
    assert "None" not in result.warnings[0]
    assert "app.missing" in result.warnings[0]


def test_followed_symlink_outside_root_is_named_by_its_link_path(
    make_project: MakeProject, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    (outside / "shared").mkdir(parents=True)
    (outside / "shared" / "util.py").write_text("")
    root = make_project({"proj/app/__init__.py": "", "proj/app/a.py": "import shared.util\n"})
    project = root / "proj"
    (project / "shared").symlink_to(outside / "shared", target_is_directory=True)

    adapter = PythonAdapter(AnalysisConfig(follow_symlinks=True))
    files = sorted(adapter.discover_files(project, pathspec.PathSpec([]), follow_symlinks=True))
    result = adapter.parse(files, project)
    assert "shared.util" in {m.name for m in result.modules}
    assert ("app.a", "shared.util", None, False) in internal(result)


def test_self_import_produces_no_edge(make_project: MakeProject) -> None:
    root = make_project({"app/__init__.py": "", "app/a.py": "import app.a\n"})
    assert internal(parse(root)) == set()


def reexports(result: ParseResult) -> set[tuple[str, str, str]]:
    return {(r.exporting_module, r.original_module, r.symbol_name) for r in result.re_exports}


def test_reexport_chain_is_detected(reexport_chain: Path) -> None:
    result = parse(reexport_chain)
    assert reexports(result) == {
        ("app", "app.core", "Engine"),
        ("app.core", "app.core.impl.engine", "Engine"),
    }
    assert ("app.consumer", "app", "Engine", False) in internal(result)


def test_reexport_cycle_is_detected(reexport_cycle: Path) -> None:
    assert reexports(parse(reexport_cycle)) == {
        ("app.a", "app.b", "Thing"),
        ("app.b", "app.a", "Thing"),
    }


def test_aliased_reexport_uses_exported_name(make_project: MakeProject) -> None:
    root = make_project(
        {"app/__init__.py": "from .engine import Engine as Motor\n", "app/engine.py": ""}
    )
    assert reexports(parse(root)) == {("app", "app.engine", "Motor")}


def test_non_reexports_are_ignored(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "from . import models\nfrom os import path\nfrom .models import *\n",
            "app/models.py": "",
            "app/views.py": "from app.models import User\n",
        }
    )
    assert reexports(parse(root)) == set()


def module_names(result: ParseResult) -> set[str]:
    return {m.name for m in result.modules}


def test_syntax_error_is_warned_and_other_files_still_parse(make_project: MakeProject) -> None:
    root = make_project(
        {"app/__init__.py": "", "app/bad.py": "def broken(:\n", "app/ok.py": "import app.bad\n"}
    )
    result = parse(root)
    assert module_names(result) == {"app", "app.ok"}
    assert internal(result) == {("app.ok", "app.bad", None, False)}
    assert len(result.warnings) == 1
    assert "bad.py" in result.warnings[0]


def test_deeply_nested_expression_is_warned_not_raised(make_project: MakeProject) -> None:
    root = make_project({"gen.py": "x = " + "+".join(["a"] * 100_000) + "\n"})
    result = parse(root)
    assert module_names(result) == set()
    assert len(result.warnings) == 1


def test_null_bytes_are_warned(make_project: MakeProject) -> None:
    root = make_project({"a.py": "x = 1\x00\n"})
    assert len(parse(root).warnings) == 1


def test_oversized_file_is_skipped_without_reading(make_project: MakeProject) -> None:
    root = make_project({"big.py": "import os\n"})
    (root / "big.py").write_bytes(b"\xff\xfe invalid utf-8 " * 10)
    result = parse(root, AnalysisConfig(max_file_size_bytes=16))
    assert module_names(result) == set()
    assert len(result.warnings) == 1
    assert "max_file_size_bytes" in result.warnings[0]


def test_undecodable_file_is_warned(make_project: MakeProject) -> None:
    root = make_project({"a.py": ""})
    (root / "a.py").write_bytes(b"x = '\xe9'\n")
    assert len(parse(root).warnings) == 1


def test_pep263_cookie_is_honoured(make_project: MakeProject) -> None:
    root = make_project({"app/__init__.py": "", "app/b.py": ""})
    (root / "app/a.py").write_bytes(b"# -*- coding: latin-1 -*-\nimport app.b  # caf\xe9\n")
    result = parse(root)
    assert internal(result) == {("app.a", "app.b", None, False)}
    assert result.warnings == []


def test_file_vanishing_after_discovery_is_warned(make_project: MakeProject) -> None:
    root = make_project({"a.py": ""})
    result = PythonAdapter().parse([root / "a.py", root / "gone.py"], root)
    assert module_names(result) == {"a"}
    assert len(result.warnings) == 1
    assert "gone.py" in result.warnings[0]


def test_circular_imports_produce_both_edges(circular_imports: Path) -> None:
    assert internal(parse(circular_imports)) == {
        ("app.a", "app.b", None, False),
        ("app.b", "app.a", None, False),
    }
