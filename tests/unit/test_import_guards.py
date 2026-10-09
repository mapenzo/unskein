from collections.abc import Callable
from pathlib import Path

from unskein.config import AnalysisConfig
from unskein.parsers.python_parser import PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]


def _guards(make_project: MakeProject, source: str) -> dict[str, bool]:
    """Parse ``app/main.py`` with ``source`` and map each internal target to is_guarded."""
    root = make_project(
        {
            "app/__init__.py": "",
            "app/main.py": source,
            **{f"app/m{i}.py": "" for i in range(1, 8)},
        }
    )
    files = sorted(root.rglob("*.py"))
    result = PythonAdapter(AnalysisConfig()).parse(files, root)
    main = next(m for m in result.modules if m.name == "app.main")
    return {edge.target: edge.is_guarded for edge in main.imports if not edge.is_external}


def test_try_with_import_error_guards_its_body(make_project: MakeProject) -> None:
    source = "try:\n    import app.m1\nexcept ImportError:\n    pass\n"
    assert _guards(make_project, source) == {"app.m1": True}


def test_broad_handlers_and_tuples_guard(make_project: MakeProject) -> None:
    source = (
        "try:\n    import app.m1\nexcept ModuleNotFoundError:\n    pass\n"
        "try:\n    import app.m2\nexcept Exception:\n    pass\n"
        "try:\n    import app.m3\nexcept BaseException:\n    pass\n"
        "try:\n    import app.m4\nexcept (ValueError, ImportError):\n    pass\n"
        "try:\n    import app.m5\nexcept:\n    pass\n"
        "try:\n    import app.m6\nexcept builtins.ImportError:\n    pass\n"
    )
    assert set(_guards(make_project, source).values()) == {True}


def test_other_handlers_do_not_guard(make_project: MakeProject) -> None:
    source = "try:\n    import app.m1\nexcept ValueError:\n    pass\n"
    assert _guards(make_project, source) == {"app.m1": False}


def test_handler_body_is_not_guarded(make_project: MakeProject) -> None:
    source = "try:\n    import app.m1\nexcept ImportError:\n    import app.m2\n"
    assert _guards(make_project, source) == {"app.m1": True, "app.m2": False}


def test_else_and_finally_are_not_guarded(make_project: MakeProject) -> None:
    source = (
        "try:\n    pass\nexcept ImportError:\n    pass\nelse:\n    import app.m1\n"
        "finally:\n    import app.m2\n"
    )
    assert _guards(make_project, source) == {"app.m1": False, "app.m2": False}


def test_guard_is_inherited_by_nested_blocks(make_project: MakeProject) -> None:
    source = (
        "try:\n    if True:\n        import app.m1\n"
        "    def f():\n        import app.m2\nexcept ImportError:\n    pass\n"
    )
    assert _guards(make_project, source) == {"app.m1": True, "app.m2": True}


def test_function_body_try_guards_lazy_imports(make_project: MakeProject) -> None:
    source = "def f():\n    try:\n        import app.m1\n    except ImportError:\n        pass\n"
    assert _guards(make_project, source) == {"app.m1": True}


def test_contextlib_suppress_guards(make_project: MakeProject) -> None:
    source = (
        "import contextlib\nfrom contextlib import suppress\n"
        "with contextlib.suppress(ImportError):\n    import app.m1\n"
        "with suppress(ModuleNotFoundError, KeyError):\n    import app.m2\n"
        "with suppress(KeyError):\n    import app.m3\n"
    )
    assert _guards(make_project, source) == {"app.m1": True, "app.m2": True, "app.m3": False}


def test_try_star_guards(make_project: MakeProject) -> None:
    source = "try:\n    import app.m1\nexcept* ImportError:\n    pass\n"
    assert _guards(make_project, source) == {"app.m1": True}


def test_plain_imports_are_not_guarded(make_project: MakeProject) -> None:
    source = "import app.m1\nfrom app import m2\n"
    assert _guards(make_project, source) == {"app.m1": False, "app.m2": False}


def test_handlers_that_always_raise_do_not_guard(make_project: MakeProject) -> None:
    source = (
        "try:\n    import app.m1\nexcept ImportError:\n    raise RuntimeError('install it')\n"
        "try:\n    import app.m2\nexcept Exception as error:\n    log(error)\n    raise\n"
        "try:\n    import app.m3\nexcept ValueError:\n    pass\n"
        "except ImportError:\n    m3 = None\n"
    )
    assert _guards(make_project, source) == {"app.m1": False, "app.m2": False, "app.m3": True}
