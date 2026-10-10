import subprocess
import sys
from pathlib import Path

import pytest

from unskein.parsers import rewrite
from unskein.parsers.rewrite import Move, MoveKind, RewriteRefusal, rewrite_source


def lazy(source: str, *lines: int) -> tuple[str, RewriteRefusal | None]:
    result = rewrite_source(source, [Move(MoveKind.LAZY, lines or (1,))])
    return result.source, result.refusals[0]


def test_moves_the_import_into_the_function_that_reads_it() -> None:
    source = "import json\n\n\ndef dump(value):\n    return json.dumps(value)\n"
    assert lazy(source) == (
        "\n\ndef dump(value):\n    import json\n    return json.dumps(value)\n",
        None,
    )


def test_inserts_after_the_docstring() -> None:
    source = 'import json\n\n\ndef dump(value):\n    """Dump."""\n    return json.dumps(value)\n'
    new, refusal = lazy(source)
    assert refusal is None
    assert '    """Dump."""\n    import json\n    return' in new


def test_every_outermost_reader_gets_the_import() -> None:
    source = (
        "import json\n\n\n"
        "def a():\n    return json.dumps(1)\n\n\n"
        "class C:\n    def m(self):\n        def inner():\n            return json.dumps(2)\n"
        "        return inner\n"
    )
    new, refusal = lazy(source)
    assert refusal is None
    assert new.count("import json") == 2
    assert "    def m(self):\n        import json\n        def inner():" in new


def test_keeps_the_alias_and_the_statement_text() -> None:
    source = "from os import path as p, sep\n\n\ndef f():\n    return p.join('a', sep)\n"
    new, refusal = lazy(source)
    assert refusal is None
    assert "    from os import path as p, sep\n" in new


def test_reindents_a_parenthesized_import() -> None:
    source = "from os import (\n    path,\n    sep,\n)\n\n\ndef f():\n    return path, sep\n"
    new, refusal = lazy(source, 1)
    assert refusal is None
    assert "def f():\n    from os import (\n        path,\n        sep,\n    )\n    return" in new


def test_keeps_crlf_line_endings() -> None:
    source = "import json\r\n\r\n\r\ndef f():\r\n    return json.dumps(1)\r\n"
    new, refusal = lazy(source)
    assert refusal is None
    assert new == "\r\n\r\ndef f():\r\n    import json\r\n    return json.dumps(1)\r\n"


def test_plans_several_moves_against_the_original_lines() -> None:
    source = (
        "import json\nimport os\n\n\ndef a():\n    return json.dumps(1)\n\n\n"
        "def b():\n    return os.getcwd()\n"
    )
    result = rewrite_source(source, [Move(MoveKind.LAZY, (2,)), Move(MoveKind.LAZY, (1,))])
    assert result.refusals == (None, None)
    assert "def a():\n    import json\n" in result.source
    assert "def b():\n    import os\n" in result.source
    assert "import json\nimport os\n\n\ndef a" not in result.source


def test_the_same_statement_in_two_moves_is_applied_once() -> None:
    source = "import json\n\n\ndef a():\n    return json.dumps(1)\n"
    result = rewrite_source(source, [Move(MoveKind.LAZY, (1,)), Move(MoveKind.LAZY, (1,))])
    assert result.refusals == (None, None)
    assert result.source.count("import json") == 1


@pytest.mark.parametrize(
    ("source", "line", "expected"),
    [
        ("import json\nx = json.dumps(1)\n", 1, RewriteRefusal.READ_AT_IMPORT),
        ("import json\n\n\n@json.x\ndef f(): ...\n", 1, RewriteRefusal.READ_AT_IMPORT),
        ("import json\n\n\ndef f(a=json.x): ...\n", 1, RewriteRefusal.READ_AT_IMPORT),
        ("import json\n\n\nclass C:\n    x = json.y\n", 1, RewriteRefusal.READ_AT_IMPORT),
        ("import json\n\n\ndef f(x: json.T): ...\n", 1, RewriteRefusal.READ_AT_IMPORT),
        ("import json\n\n\ndef f(json):\n    return json\n", 1, RewriteRefusal.NAME_REUSED),
        (
            "import json\n\n\ndef f():\n    json = 1\n    return json\n",
            1,
            RewriteRefusal.NAME_REUSED,
        ),
        (
            "import json\n\n\ndef f():\n    global json\n    return json\n",
            1,
            RewriteRefusal.NAME_REUSED,
        ),
        (
            "import json\njson = None\n\n\ndef f():\n    return json\n",
            1,
            RewriteRefusal.NAME_REUSED,
        ),
        (
            "import json\n__all__ = ['json']\n\n\ndef f():\n    return json\n",
            1,
            RewriteRefusal.EXPORTED,
        ),
        ("import json\n\n\ndef f(): return json\n", 1, RewriteRefusal.INLINE_BODY),
        ("import json\n\nx = 1\n", 1, RewriteRefusal.NO_READER),
        (
            "try:\n    import json\nexcept ImportError:\n    json = None\n\n\n"
            "def f():\n    return json\n",
            2,
            RewriteRefusal.NESTED_IMPORT,
        ),
        ("from os import *\n\n\ndef f():\n    return sep\n", 1, RewriteRefusal.STAR_IMPORT),
        (
            "import json; import os\n\n\ndef f():\n    return json, os\n",
            1,
            RewriteRefusal.MULTIPLE_STATEMENTS,
        ),
        (
            "import json;\n\n\ndef f():\n    return json\n",
            1,
            RewriteRefusal.MULTIPLE_STATEMENTS,
        ),
    ],
    ids=[
        "module_level_read",
        "decorator",
        "default",
        "class_body",
        "evaluated_annotation",
        "parameter",
        "assignment",
        "global",
        "second_binding",
        "in_all",
        "inline_body",
        "no_reader",
        "inside_try",
        "star",
        "two_statements",
        "trailing_semicolon",
    ],
)
def test_refuses_what_it_cannot_move_safely(
    source: str, line: int, expected: RewriteRefusal
) -> None:
    new, refusal = lazy(source, line)
    assert (new, refusal) == (source, expected)


def test_a_postponed_annotation_does_not_count_as_a_read_at_import() -> None:
    source = (
        "from __future__ import annotations\nimport json\n\n\n"
        "def f(x: json.T):\n    return json.dumps(x)\n"
    )
    new, refusal = lazy(source, 2)
    assert refusal is None
    assert "def f(x: json.T):\n    import json\n" in new


def test_a_wrong_line_is_unreadable() -> None:
    assert lazy("import json\n", 7) == ("import json\n", RewriteRefusal.UNREADABLE)


def test_broken_source_is_unreadable() -> None:
    assert lazy("def (:\n") == ("def (:\n", RewriteRefusal.UNREADABLE)


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


def test_a_lazy_move_breaks_the_cycle_and_both_modules_still_import(tmp_path: Path) -> None:
    (tmp_path / "pk").mkdir()
    (tmp_path / "pk" / "__init__.py").write_text("")
    first = "from pk.b import helper\n\nVALUE = helper()\n"
    second = (
        "from pk.a import VALUE\n\n\ndef helper():\n    return 1\n\n\n"
        "def show():\n    return VALUE\n"
    )
    (tmp_path / "pk" / "a.py").write_text(first)
    (tmp_path / "pk" / "b.py").write_text(second)
    assert run_import(tmp_path, "pk.b").returncode != 0
    new, refusal = lazy(second)
    assert refusal is None
    (tmp_path / "pk" / "b.py").write_text(new)
    assert run_import(tmp_path, "pk.b").returncode == 0
    assert run_import(tmp_path, "pk.a").returncode == 0


def test_a_rewrite_that_does_not_parse_is_discarded(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = rewrite._Edit(0, 1, ("def (:\n",))
    monkeypatch.setattr(rewrite, "_plan_lazy", lambda ctx, statements: [broken])
    source = "import json\n\n\ndef f():\n    return json\n"
    assert lazy(source) == (source, RewriteRefusal.UNREADABLE)
