import subprocess
import sys
from pathlib import Path

import pytest

from unskein.parsers.rewrite import Move, MoveKind, RewriteRefusal, rewrite_source

FUTURE = "from __future__ import annotations\n"


def guard(source: str, *lines: int) -> tuple[str, RewriteRefusal | None]:
    result = rewrite_source(source, [Move(MoveKind.TYPE_CHECKING, lines or (1,))])
    return result.source, result.refusals[0]


def test_moves_the_import_under_type_checking_and_adds_the_typing_import() -> None:
    source = FUTURE + "from pk.b import B\n\n\ndef f(x: B) -> B:\n    return x\n"
    assert guard(source, 2) == (
        FUTURE + "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from pk.b import B\n\n\n"
        "def f(x: B) -> B:\n    return x\n",
        None,
    )


def test_reuses_an_existing_typing_import() -> None:
    source = FUTURE + "from typing import TYPE_CHECKING\nfrom pk.b import B\n\n\ndef f(x: B): ...\n"
    new, refusal = guard(source, 3)
    assert refusal is None
    assert new.count("from typing import TYPE_CHECKING") == 1
    assert "if TYPE_CHECKING:\n    from pk.b import B\n" in new


def test_quoted_annotations_need_no_future_import() -> None:
    source = "from pk.b import B\n\n\ndef f(x: 'B') -> 'B':\n    return x\n"
    new, refusal = guard(source)
    assert refusal is None
    assert "if TYPE_CHECKING:\n    from pk.b import B\n" in new


def test_two_moves_add_one_typing_import() -> None:
    source = FUTURE + "from a import A\nfrom b import B\n\n\ndef f(x: A, y: B): ...\n"
    result = rewrite_source(
        source,
        [Move(MoveKind.TYPE_CHECKING, (2,)), Move(MoveKind.TYPE_CHECKING, (3,))],
    )
    assert result.refusals == (None, None)
    assert result.source.count("from typing import TYPE_CHECKING") == 1
    assert result.source.count("if TYPE_CHECKING:") == 2


@pytest.mark.parametrize(
    ("source", "line", "expected"),
    [
        ("from pk.b import B\n\n\ndef f(x: B): ...\n", 1, RewriteRefusal.ANNOTATIONS_EVALUATED),
        (
            FUTURE + "from pk.b import B\n\n\ndef f():\n    return B()\n",
            2,
            RewriteRefusal.READ_AT_RUNTIME,
        ),
        (FUTURE + "from pk.b import B\nx = B()\n", 2, RewriteRefusal.READ_AT_RUNTIME),
        (
            FUTURE + "TYPE_CHECKING = False\nfrom pk.b import B\n\n\ndef f(x: B): ...\n",
            3,
            RewriteRefusal.NAME_REUSED,
        ),
        (
            FUTURE
            + "from typing import TYPE_CHECKING\nTYPE_CHECKING = False\n"
            + "from pk.b import B\n\n\ndef f(x: B): ...\n",
            4,
            RewriteRefusal.NAME_REUSED,
        ),
        (
            FUTURE + "from pk.b import B\nB = None\n\n\ndef f(x: B): ...\n",
            2,
            RewriteRefusal.NAME_REUSED,
        ),
        (
            FUTURE + "from pk.b import B\n__all__ = ['B']\n\n\ndef f(x: B): ...\n",
            2,
            RewriteRefusal.EXPORTED,
        ),
        (
            FUTURE + "try:\n    from pk.b import B\nexcept ImportError:\n    B = None\n",
            3,
            RewriteRefusal.NESTED_IMPORT,
        ),
    ],
    ids=[
        "evaluated_annotation",
        "function_read",
        "module_read",
        "guard_rebound",
        "guard_imported_and_rebound",
        "name_rebound",
        "in_all",
        "inside_try",
    ],
)
def test_refuses_what_it_cannot_move_safely(
    source: str, line: int, expected: RewriteRefusal
) -> None:
    new, refusal = guard(source, line)
    assert refusal is expected
    assert new == source


def run_import(root: Path, module: str) -> subprocess.CompletedProcess[str]:
    code = (
        "import sys, importlib; sys.path.insert(0, sys.argv[1]);"
        " importlib.import_module(sys.argv[2])"
    )
    return subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, str(root), module],
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_postponed_cycle_imports_after_the_move_on_every_python(tmp_path: Path) -> None:
    (tmp_path / "pk").mkdir()
    (tmp_path / "pk" / "__init__.py").write_text("")
    a = FUTURE + "from pk.b import B\n\n\nclass A:\n    def f(self, x: B) -> B:\n        return x\n"
    b = FUTURE + "from pk.a import A\n\n\nclass B:\n    def g(self) -> A:\n        return A()\n"
    (tmp_path / "pk" / "a.py").write_text(a)
    (tmp_path / "pk" / "b.py").write_text(b)
    assert run_import(tmp_path, "pk.a").returncode != 0
    new, refusal = guard(a, 2)
    assert refusal is None
    (tmp_path / "pk" / "a.py").write_text(new)
    assert run_import(tmp_path, "pk.a").returncode == 0
    assert run_import(tmp_path, "pk.b").returncode == 0
