import ast
from collections.abc import Callable
from pathlib import Path

import pathspec

from unskein.config import AnalysisConfig
from unskein.parsers.exports import module_exports
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import WarningCode
from unskein.parsers.python_parser import PythonAdapter
from unskein.parsers.usage import collect_read_names

MakeProject = Callable[[dict[str, str]], Path]
FIXTURE = Path(__file__).parent.parent / "fixtures" / "star_project"


def _parse(root: Path = FIXTURE):
    """Discover and parse a project, before re-export resolution."""
    adapter = PythonAdapter(AnalysisConfig())
    return adapter.parse(sorted(adapter.discover_files(root, pathspec.PathSpec([]))), root)


def _module(result, name: str):
    """Return one parsed module."""
    (found,) = [m for m in result.modules if m.name == name]
    return found


def test_dynamic_all_is_detected() -> None:
    assert module_exports(ast.parse("__all__ = [n for n in 'ab']\n")).has_dynamic_all
    assert module_exports(ast.parse("__all__ = ['a']\n__all__.append('b')\n")).has_dynamic_all
    assert module_exports(ast.parse("__all__ = ['a']\n__all__ += x\n")).has_dynamic_all
    assert not module_exports(ast.parse("__all__ = ['a']\n__all__ += ['b']\n")).has_dynamic_all
    assert not module_exports(ast.parse("x = 1\n")).has_dynamic_all


def test_read_names_include_loads_and_string_annotations_not_docstrings() -> None:
    tree = ast.parse('"""Doc mentions Hidden."""\n\ndef f(x: "Typed[Other]"):\n    return y\n')
    assert collect_read_names(tree) == ("Other", "Typed", "y")


def test_non_facade_and_self_stars_are_recorded_in_code_order() -> None:
    result = _parse()
    assert _module(result, "app.both").wildcards == ((1, "app.types"), (2, "app.models"))
    assert _module(result, "app.sub").wildcards == ((1, "app.sub"),)
    assert _module(result, "app").wildcards == ()
    assert _module(result, "app.ext").wildcards == ()


def test_star_reads_are_kept_only_for_modules_with_wildcards() -> None:
    result = _parse()
    assert "D" in _module(result, "app.annot").star_reads
    assert _module(result, "app.models").star_reads == ()


def test_only_unresolvable_stars_warn_after_resolution() -> None:
    resolved = resolve_indirection(_parse())
    stars = [
        (w.path.name, w.line, w.detail)
        for w in resolved.warnings
        if w.code is WarningCode.STAR_IMPORT
    ]
    assert stars == [("uses_dynamic.py", 1, "app.dynamic")]


def test_star_of_a_module_that_was_not_parsed_warns(make_project: MakeProject) -> None:
    root = make_project({"app/__init__.py": "", "app/a.py": "from app.gone import *\n"})
    resolved = resolve_indirection(_parse(root))
    assert [w.detail for w in resolved.warnings if w.code is WarningCode.STAR_IMPORT] == [
        "app.gone"
    ]
