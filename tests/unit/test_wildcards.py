import ast
from collections.abc import Callable
from pathlib import Path

import pathspec
import pytest

from unskein.config import AnalysisConfig
from unskein.parsers.exports import module_exports, module_surface
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import WarningCode
from unskein.parsers.python_parser import PythonAdapter
from unskein.parsers.usage import collect_read_names

MakeProject = Callable[[dict[str, str]], Path]
FIXTURE = Path(__file__).parent.parent / "fixtures" / "star_project"


def _parse(root: Path = FIXTURE):
    """Discover and parse a project, before re-export resolution."""
    adapter = PythonAdapter(AnalysisConfig(star_fixes=True))
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
    assert _module(result, "app.both").stars.statements == ((1, "app.types"), (2, "app.models"))
    assert _module(result, "app.sub").stars.statements == ((1, "app.sub"),)
    assert _module(result, "app").stars.statements == ()
    assert _module(result, "app.ext").stars.statements == ()


def test_star_reads_are_kept_only_for_modules_with_wildcards() -> None:
    result = _parse()
    assert "D" in _module(result, "app.annot").stars.reads
    assert _module(result, "app.models").stars.reads == ()


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


@pytest.mark.parametrize(
    "source",
    [
        "__all__ = ['a']\n__all__.insert(0, 'b')\n",
        "__all__ = ['a']\n__all__.remove('a')\n",
        "__all__ = ['a']\n__all__[:] = ['b']\n",
        "__all__ = ['a']\nif x:\n    __all__ = ['b']\n",
    ],
)
def test_every_change_to_all_that_cannot_be_read_is_dynamic(source: str) -> None:
    assert module_exports(ast.parse(source)).has_dynamic_all


@pytest.mark.parametrize(
    ("source", "conditional"),
    [
        (
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from x import Foo\nB = 1\n",
            ("Foo",),
        ),
        ("X: int\nY = 1\n", ("X",)),
        ("value = 1\nCONST = value\ndel value\n", ("value",)),
        ("for item in []:\n    pass\n", ("item",)),
        ("def f():\n    global G\n    G = 1\n", ("G",)),
        ("try:\n    import fast as impl\nexcept ImportError:\n    impl = None\n", ("impl",)),
        ("A = 1\nclass B: ...\n", ()),
    ],
)
def test_names_that_may_be_unbound_are_conditional(source: str, conditional) -> None:
    assert module_surface(ast.parse(source))[0] == conditional


@pytest.mark.parametrize(
    "source",
    ["if x:\n    from a import *\n", "globals()['X'] = 1\n", "exec('X = 1')\n"],
)
def test_a_star_of_a_module_that_writes_its_namespace_is_uncertain(source: str) -> None:
    assert module_surface(ast.parse(source))[1]
