import ast
from collections.abc import Callable
from pathlib import Path

import pathspec
import pytest

from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import ImportKind, ModuleInfo
from unskein.parsers.python_parser import PythonAdapter
from unskein.parsers.usage import (
    NO_EVIDENCE,
    ImportEvidence,
    UseContext,
    bound_names_by_line,
    collect_import_evidence,
    collect_use_contexts,
)

MakeProject = Callable[[dict[str, str]], Path]
A, F, M = UseContext.ANNOTATION, UseContext.FUNCTION, UseContext.MODULE

CONTEXT_CASES = {
    "annotation_only": ("def f(x: Engine) -> Engine: ...\n", {A}),
    "function_body": ("def f():\n    return Engine()\n", {F}),
    "module_level": ("x = Engine()\n", {M}),
    "class_base": ("class C(Engine): ...\n", {M}),
    "decorator_and_default": ("@Engine\ndef f(x=Engine): ...\n", {M}),
    "annotated_assignment": ("x: Engine = 1\n", {A}),
    "quoted_annotation": ("def f(x: 'list[Engine]'): ...\n", {A}),
    "lambda_body": ("g = lambda: Engine()\n", {F}),
    "method_annotation": ("class C:\n    def m(self) -> Engine: ...\n", {A}),
    "mixed": ("def f(x: Engine):\n    return Engine()\n", {A, F}),
    "function_type_param_bound": ("def f[T: Engine](x): ...\n", {M}),
    "class_type_param_bound": ("class C[T: Engine]: ...\n", {M}),
    "unused": ("x = 1\n", set()),
}


@pytest.mark.parametrize(("source", "expected"), CONTEXT_CASES.values(), ids=CONTEXT_CASES.keys())
def test_use_context_follows_where_the_name_is_read(source: str, expected: set) -> None:
    assert collect_use_contexts(ast.parse(source), ["Engine"])["Engine"] == frozenset(expected)


def test_annotated_assignment_value_keeps_its_own_context() -> None:
    contexts = collect_use_contexts(ast.parse("x: Engine = make()\n"), ["Engine", "make"])
    assert (contexts["Engine"], contexts["make"]) == (frozenset({A}), frozenset({M}))


def test_bound_names_by_line() -> None:
    source = "import a.b\nimport c as d\nfrom e import f, g as h\nfrom i import *\n"
    assert bound_names_by_line(ast.parse(source)) == {1: ("a",), 2: ("d",), 3: ("f", "h")}


def parsed_module(root: Path, name: str) -> ModuleInfo:
    """Parse and resolve a project, then return one of its modules.

    Args:
        root: Project directory.
        name: Dotted module name.

    Returns:
        The resolved module.
    """
    adapter = PythonAdapter()
    files = sorted(adapter.discover_files(root, pathspec.PathSpec([])))
    resolved = resolve_indirection(adapter.parse(files, root))
    return next(m for m in resolved.modules if m.name == name)


def test_evidence_gathers_lines_symbols_and_contexts(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/a.py": "from app.b import B, C\n\ndef run():\n    return B(), C()\n",
            "app/b.py": "class B: ...\nclass C: ...\n",
        }
    )
    module = parsed_module(root, "app.a")
    evidence = collect_import_evidence(
        module, [("app.a", "app.b")], kinds={ImportKind.MODULE}, encoding=None
    )
    assert evidence == {
        ("app.a", "app.b"): ImportEvidence(
            module.file_path, (1,), ("B", "C"), frozenset({UseContext.FUNCTION})
        )
    }


def test_evidence_ignores_statements_of_other_kinds(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/a.py": (
                "from typing import TYPE_CHECKING\nfrom app.b import B\n"
                "if TYPE_CHECKING:\n    from app.b import C\nx = B\n"
            ),
            "app/b.py": "class B: ...\nclass C: ...\n",
        }
    )
    module = parsed_module(root, "app.a")
    [evidence] = collect_import_evidence(
        module, [("app.a", "app.b")], kinds={ImportKind.MODULE}, encoding=None
    ).values()
    assert (evidence.lines, evidence.symbols) == ((2,), ("B",))


def test_unreadable_file_gives_evidence_without_contexts(make_project: MakeProject) -> None:
    root = make_project(
        {"app/__init__.py": "", "app/a.py": "from app.b import B\n", "app/b.py": ""}
    )
    module = parsed_module(root, "app.a")
    module.file_path.write_text("def broken(:\n", encoding="utf-8")
    [evidence] = collect_import_evidence(
        module, [("app.a", "app.b")], kinds={ImportKind.MODULE}, encoding=None
    ).values()
    assert (evidence.lines, evidence.symbols, evidence.contexts) == ((1,), ("B",), frozenset())


def test_no_evidence_is_empty() -> None:
    assert ImportEvidence(None, (), (), frozenset()) == NO_EVIDENCE


@pytest.mark.parametrize(
    ("header", "expected"),
    [("", False), ("from __future__ import annotations\n", True)],
    ids=["evaluated_annotations", "postponed_annotations"],
)
def test_evidence_tells_whether_annotations_are_postponed(
    make_project: MakeProject, header: str, expected: bool
) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/a.py": f"{header}from app.b import B\n\n\ndef f(x: B):\n    return B()\n",
            "app/b.py": "class B: ...\n",
        }
    )
    [evidence] = collect_import_evidence(
        parsed_module(root, "app.a"), [("app.a", "app.b")], kinds={ImportKind.MODULE}, encoding=None
    ).values()
    assert evidence.postponed_annotations is expected
