import pytest

from unskein.parsers.rewrite import Move, MoveKind, RewriteRefusal, rewrite_source


def lazy(source: str, *lines: int) -> tuple[str, RewriteRefusal | None]:
    result = rewrite_source(source, [Move(MoveKind.LAZY, lines or (1,))])
    return result.source, result.refusals[0]


def test_vars_of_another_object_keeps_the_move_safe() -> None:
    source = "import json\n\n\ndef dump(value):\n    return json.dumps(vars(value))\n"
    new, refusal = lazy(source)
    assert refusal is None
    assert new == "\n\ndef dump(value):\n    import json\n    return json.dumps(vars(value))\n"


@pytest.mark.parametrize(
    "call",
    ["globals()", "vars()", "exec('x = 1')", "vars(sys.modules[__name__])"],
    ids=["globals", "bare_vars", "exec", "vars_of_the_module"],
)
def test_a_call_that_can_write_the_module_namespace_refuses(call: str) -> None:
    source = f"import json\nimport sys\n\n\ndef dump(v):\n    return json.dumps(v)\n\n\n{call}\n"
    assert lazy(source)[1] is RewriteRefusal.NAME_REUSED


def test_a_star_import_inside_a_block_refuses() -> None:
    source = (
        "import json\n\ntry:\n    from os import *\nexcept ImportError:\n    pass\n\n\n"
        "def dump(v):\n    return json.dumps(v)\n"
    )
    assert lazy(source)[1] is RewriteRefusal.NAME_REUSED


def test_sibling_submodule_imports_do_not_block_the_move() -> None:
    source = "import pkg\nimport pkg.sub\n\n\ndef f():\n    return pkg.thing, pkg.sub.x\n"
    new, refusal = lazy(source, 1)
    assert refusal is None
    assert new == "import pkg.sub\n\n\ndef f():\n    import pkg\n    return pkg.thing, pkg.sub.x\n"


@pytest.mark.parametrize(
    "extra",
    ["pkg = other\n", "import pkg\n", "import pkg.sub as pkg\n", "if flag:\n    import pkg.sub\n"],
    ids=["assigned", "imported_twice", "renamed_submodule", "sibling_in_a_block"],
)
def test_other_ways_of_binding_the_name_still_refuse(extra: str) -> None:
    source = f"import pkg\n{extra}\n\ndef f():\n    return pkg.thing\n"
    assert lazy(source, 1)[1] is RewriteRefusal.NAME_REUSED


def test_a_reader_that_imports_the_module_itself_is_left_alone() -> None:
    source = (
        "import pkg\n\n\ndef a():\n    import pkg\n    return pkg.x\n\n\n"
        "def b():\n    return pkg.y\n"
    )
    new, refusal = lazy(source)
    assert refusal is None
    assert new == (
        "\n\ndef a():\n    import pkg\n    return pkg.x\n\n\n"
        "def b():\n    import pkg\n    return pkg.y\n"
    )


def test_a_reader_importing_inside_a_try_block_is_left_alone() -> None:
    source = (
        "import pkg\n\n\ndef a():\n    try:\n        import pkg\n        return pkg.x\n"
        "    except ImportError:\n        return None\n"
    )
    new, refusal = lazy(source)
    assert refusal is None
    assert new == (
        "\n\ndef a():\n    try:\n        import pkg\n        return pkg.x\n"
        "    except ImportError:\n        return None\n"
    )


def test_a_reader_that_reads_before_its_own_import_refuses() -> None:
    source = "import pkg\n\n\ndef a():\n    x = pkg.x\n    import pkg\n    return x\n"
    assert lazy(source)[1] is RewriteRefusal.NAME_REUSED


def test_a_reader_that_imports_and_also_assigns_the_name_refuses() -> None:
    source = "import pkg\n\n\ndef a():\n    import pkg\n    pkg = pkg.x\n    return pkg\n"
    assert lazy(source)[1] is RewriteRefusal.NAME_REUSED
