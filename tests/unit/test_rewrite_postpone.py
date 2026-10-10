import ast

import pytest

from unskein.parsers.rewrite import Move, MoveKind, RewriteRefusal, rewrite_source

FUTURE = "from __future__ import annotations\n"
TYPING = "from typing import TYPE_CHECKING\n"


def postponed(
    source: str, *lines: int, kind: MoveKind = MoveKind.TYPE_CHECKING
) -> tuple[str, RewriteRefusal | None]:
    result = rewrite_source(source, [Move(kind, lines or (1,), postpone=True)])
    return result.source, result.refusals[0]


def test_postpones_and_moves_an_annotation_only_import_under_type_checking() -> None:
    source = "from app.b import B\n\n\ndef f(x: B) -> B:\n    return x\n"
    assert postponed(source) == (
        FUTURE
        + TYPING
        + "if TYPE_CHECKING:\n    from app.b import B\n\n\ndef f(x: B) -> B:\n    return x\n",
        None,
    )


def test_postpones_and_moves_an_annotation_and_function_import_into_the_function() -> None:
    source = "from app.b import B\n\n\ndef f(x: B):\n    return B()\n"
    assert postponed(source, kind=MoveKind.LAZY) == (
        FUTURE + "\n\ndef f(x: B):\n    from app.b import B\n    return B()\n",
        None,
    )


def test_the_future_import_goes_after_the_docstring_and_before_decorators() -> None:
    source = '"""Doc."""\nimport functools\n\n\n@functools.cache\ndef f(x: B):\n    return B()\n'
    source = source.replace("import functools\n", "from app.b import B\n").replace(
        "@functools.cache\n", "@decorate\n"
    )
    new, refusal = postponed(source, 2, kind=MoveKind.LAZY)
    assert refusal is None
    assert new.startswith('"""Doc."""\n' + FUTURE)
    ast.parse(new)


def test_a_shebang_and_a_coding_cookie_stay_first() -> None:
    source = (
        "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\n"
        "from app.b import B\n\n\ndef f(x: B) -> B:\n    return x\n"
    )
    new, refusal = postponed(source, 3)
    assert refusal is None
    assert new.startswith("#!/usr/bin/env python\n# -*- coding: utf-8 -*-\n" + FUTURE)
    ast.parse(new)


def test_an_existing_future_import_is_not_repeated() -> None:
    source = FUTURE + "from app.b import B\n\n\ndef f(x: B) -> B:\n    return x\n"
    new, refusal = postponed(source, 2)
    assert refusal is None
    assert new.count("from __future__ import annotations") == 1


def test_two_postponed_moves_add_one_future_import() -> None:
    source = "from app.b import B\nfrom app.c import C\n\n\ndef f(x: B, y: C) -> B:\n    return x\n"
    result = rewrite_source(
        source,
        [
            Move(MoveKind.TYPE_CHECKING, (1,), postpone=True),
            Move(MoveKind.TYPE_CHECKING, (2,), postpone=True),
        ],
    )
    assert result.refusals == (None, None)
    assert result.source.count("from __future__ import annotations") == 1
    ast.parse(result.source)


@pytest.mark.parametrize(
    "extra",
    [
        "from pydantic import BaseModel\n",
        "from functools import singledispatch\n",
        "import typing\n\nHINTS = typing.get_type_hints(print)\n",
        "NAMES = f.__annotations__\n",
    ],
    ids=["pydantic", "singledispatch", "get_type_hints", "dunder_annotations"],
)
def test_a_module_that_may_read_annotations_at_run_time_refuses(extra: str) -> None:
    source = f"from app.b import B\n{extra}\n\ndef f(x: B) -> B:\n    return x\n"
    new, refusal = postponed(source)
    assert (new, refusal) == (source, RewriteRefusal.RUNTIME_ANNOTATIONS)


def test_a_docstring_sharing_the_first_statement_line_cannot_take_the_future_import() -> None:
    source = '"""Doc."""; import os\nfrom app.b import B\n\n\ndef f(x: B) -> B:\n    return x\n'
    new, refusal = postponed(source, 2)
    assert refusal is not None
    assert new == source


def test_postponing_does_not_hide_a_function_level_read_from_a_type_checking_move() -> None:
    source = "from app.b import B\n\n\ndef f(x: B):\n    return B()\n"
    assert postponed(source)[1] is RewriteRefusal.READ_AT_RUNTIME
