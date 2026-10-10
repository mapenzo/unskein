import ast

import pytest

from unskein.parsers.rewrite import (
    Move,
    MoveKind,
    RewriteRefusal,
    import_time_attributes,
    rewrite_source,
)

BOOM = (("Boom", "app.errors"),)
USER = "import app\n\nERRORS = (app.Boom,)\n\n\ndef use():\n    return app\n"


def bypass(
    source: str, definers: tuple[tuple[str, str], ...] = BOOM, line: int = 1
) -> tuple[str, RewriteRefusal | None]:
    result = rewrite_source(source, [Move(MoveKind.BYPASS, (line,), definers=definers)])
    return result.source, result.refusals[0]


def test_an_import_time_read_becomes_a_direct_import_and_functions_keep_the_package() -> None:
    assert bypass(USER) == (
        "from app.errors import Boom\n\nERRORS = (Boom,)\n\n\n"
        "def use():\n    import app\n    return app\n",
        None,
    )


def test_a_module_with_no_function_reads_drops_the_package_import() -> None:
    new, refusal = bypass("import app\n\nERRORS = (app.Boom,)\n")
    assert (new, refusal) == ("from app.errors import Boom\n\nERRORS = (Boom,)\n", None)


def test_several_attributes_on_one_line_are_all_replaced() -> None:
    definers = (("A", "app.x"), ("B", "app.y"))
    new, refusal = bypass("import app\n\nT = (app.A, app.B, app.A)\n", definers)
    assert refusal is None
    assert new == "from app.x import A\nfrom app.y import B\n\nT = (A, B, A)\n"


def test_class_bodies_decorators_and_defaults_are_import_time_reads() -> None:
    source = (
        "import app\n\n\n@app.deco\nclass C:\n    base = app.Base\n\n    def f(self, x=app.Boom):\n"
        "        return x\n"
    )
    definers = (("deco", "app.d"), ("Base", "app.b"), ("Boom", "app.errors"))
    new, refusal = bypass(source, definers)
    assert refusal is None
    assert "@deco\nclass C:\n    base = Base\n" in new
    assert "def f(self, x=Boom):" in new
    ast.parse(new)


def test_the_attributes_read_at_import_are_listed() -> None:
    tree = ast.parse(USER + "\n\ndef g():\n    return app.Late\n")
    assert import_time_attributes(tree, {"app"}) == frozenset({"Boom"})


def test_an_attribute_without_a_definer_is_a_mutable_attribute() -> None:
    assert bypass(USER, definers=()) == (USER, RewriteRefusal.MUTABLE_ATTRIBUTE)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import app\n\nX = app\n", RewriteRefusal.READ_AT_IMPORT),
        ("import app\n\napp.setting = 1\nERRORS = (app.Boom,)\n", RewriteRefusal.READ_AT_IMPORT),
        ("import app\n\n\ndef f(x: app.Boom): ...\n", RewriteRefusal.READ_AT_IMPORT),
        ("import app\nBoom = 1\n\nERRORS = (app.Boom,)\n", RewriteRefusal.NAME_REUSED),
        ("import app\n\nERRORS = (app.Boom, Boom)\n", RewriteRefusal.NAME_REUSED),
        (
            "import app\n\nERRORS = (app.Boom,)\n\n\ndef f(Boom):\n    return app\n",
            RewriteRefusal.NAME_REUSED,
        ),
        ("import app, os\n\nERRORS = (app.Boom,)\n", RewriteRefusal.UNREADABLE),
        ("import app.sub\n\nERRORS = (app.Boom,)\n", RewriteRefusal.UNREADABLE),
        ("import app\n\nx = 1\n", RewriteRefusal.NO_READER),
    ],
    ids=[
        "the_package_itself_is_read",
        "an_attribute_is_assigned",
        "evaluated_annotation",
        "the_name_is_bound_in_the_module",
        "the_name_is_already_read_bare",
        "a_function_binds_the_name",
        "several_aliases",
        "a_submodule_import",
        "nothing_is_read",
    ],
)
def test_what_a_bypass_cannot_rewrite_safely_is_refused(
    source: str, expected: RewriteRefusal
) -> None:
    assert bypass(source) == (source, expected)
