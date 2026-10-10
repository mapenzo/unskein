import pytest
from test_api_leaks import LIB, analyzed

from unskein.graph.leaks import LeakAction, LeakFix, LeakKind, LeakNoFix


def _fixes(make_project, files: dict[str, str]) -> list[LeakFix]:
    root = make_project({**LIB, **files})
    return [fix for leak in analyzed(root).leaks for fix in leak.fixes]


def test_a_name_offered_by_an_ancestor_facade_gets_the_facade_import(make_project) -> None:
    (fix,) = _fixes(make_project, {"app/a.py": "from lib.core.logger import Logger\n"})
    assert (fix.action, fix.facade, fix.symbol, fix.alias) == (
        LeakAction.FACADE_IMPORT,
        "lib",
        "Logger",
        None,
    )


def test_the_alias_is_kept(make_project) -> None:
    (fix,) = _fixes(make_project, {"app/a.py": "from lib.core.logger import Logger as L\n"})
    assert (fix.facade, fix.alias) == ("lib", "L")


def test_each_name_of_a_statement_is_judged_on_its_own(make_project) -> None:
    fixes = _fixes(make_project, {"app/a.py": "from lib.core.logger import Logger, Other\n"})
    assert [fix.symbol for fix in fixes] == ["Logger"]


def test_a_sibling_facade_is_not_an_ancestor(make_project) -> None:
    files = {
        "lib/_hidden.py": "class Hidden:\n    pass\n",
        "other/__init__.py": "from lib._hidden import Hidden\n",
        "app/a.py": "from lib._hidden import Hidden\n",
    }
    (fix,) = [f for f in _fixes(make_project, files) if f.importer == "app.a"]
    assert (fix.action, fix.reason) == (LeakAction.NO_FIX, LeakNoFix.NOT_ANCESTOR)


def test_a_guarded_reexport_gets_no_fix(make_project) -> None:
    files = {
        "lib/__init__.py": (
            "try:\n    from lib.core.logger import Logger\nexcept ImportError:\n    Logger = None\n"
        ),
        "app/a.py": "from lib.core.logger import Logger\n",
    }
    (fix,) = _fixes(make_project, files)
    assert (fix.action, fix.reason) == (LeakAction.NO_FIX, LeakNoFix.GUARDED)


def test_a_rebound_name_gets_no_fix(make_project) -> None:
    files = {
        "lib/_hidden.py": "class Hidden:\n    pass\n",
        "lib/__init__.py": (
            "from lib._hidden import Hidden\n\n\ndef wrap(cls):\n    return cls\n\n\n"
            "Hidden = wrap(Hidden)\n"
        ),
        "app/a.py": "from lib._hidden import Hidden\n",
    }
    (fix,) = _fixes(make_project, files)
    assert (fix.action, fix.reason) == (LeakAction.NO_FIX, LeakNoFix.REBOUND)


@pytest.mark.parametrize(
    ("facade", "reason"),
    [
        (
            "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n"
            "    from lib._hidden import Hidden\n",
            LeakNoFix.CONDITIONAL,
        ),
        ("def f():\n    from lib._hidden import Hidden\n", LeakNoFix.CONDITIONAL),
        ("from lib._hidden import Other as Hidden\n", LeakNoFix.RENAMED),
        ("from lib._hidden import Hidden\n\ndel Hidden\n", LeakNoFix.REBOUND),
        ("from lib._hidden import Hidden\nimport json as Hidden\n", LeakNoFix.REBOUND),
        (
            "from lib._hidden import Hidden\n\ntry:\n    1 / 0\n"
            "except ZeroDivisionError as Hidden:\n    pass\n",
            LeakNoFix.REBOUND,
        ),
        ("from lib._hidden import Hidden\n\nglobals()['Hidden'] = 1\n", LeakNoFix.REBOUND),
        ("from lib._hidden import *\nfrom lib.other import *\n", LeakNoFix.REBOUND),
    ],
)
def test_a_facade_that_does_not_plainly_offer_the_name_gets_the_reason(
    make_project, facade: str, reason: LeakNoFix
) -> None:
    files = {
        "lib/_hidden.py": "class Hidden:\n    pass\n\n\nclass Other:\n    pass\n",
        "lib/other.py": "class Hidden:\n    pass\n",
        "lib/__init__.py": facade,
        "app/a.py": "from lib._hidden import Hidden\n",
    }
    (fix,) = _fixes(make_project, files)
    assert (fix.action, fix.reason) == (LeakAction.NO_FIX, reason)


@pytest.mark.parametrize(
    "facade",
    [
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n"
        "    from lib.core.logger import Logger\n",
        "from lib.core.logger import Other as Logger\n",
        "from lib.core.logger import Logger\n\ndel Logger\n",
    ],
)
def test_a_facade_that_does_not_really_offer_the_name_is_no_bypass(
    make_project, facade: str
) -> None:
    files = {"lib/__init__.py": facade, "app/a.py": "from lib.core.logger import Logger\n"}
    assert _fixes(make_project, files) == []


def test_a_submodule_with_the_name_of_the_export_gets_no_fix(make_project) -> None:
    files = {
        "lib/_impl.py": "def util():\n    return 1\n",
        "lib/util.py": "X = 1\n",
        "lib/__init__.py": "from lib._impl import util\n",
        "app/a.py": "from lib._impl import util\n",
    }
    (fix,) = _fixes(make_project, files)
    assert (fix.action, fix.reason) == (LeakAction.NO_FIX, LeakNoFix.REBOUND)


def test_the_consumers_own_package_is_not_an_offer(make_project) -> None:
    files = {"app/__init__.py": "from lib._private import SECRET\n"}
    (fix,) = _fixes(make_project, files)
    assert (fix.action, fix.reason) == (LeakAction.NO_FIX, LeakNoFix.NO_PUBLIC_PATH)


def test_a_whole_module_import_read_through_an_attribute_is_never_reported(make_project) -> None:
    files = {
        "lib/core/__init__.py": "from lib.core.logger import Logger\n",
        "app/a.py": "import lib.core as c\nprint(c.Logger)\n",
    }
    assert _fixes(make_project, files) == []


def test_a_facade_that_imports_the_consumer_gets_no_fix(make_project) -> None:
    files = {
        "lib/__init__.py": "from lib.core.logger import Logger\nimport app.a\n",
        "app/a.py": "from lib.core.logger import Logger\n",
    }
    (fix,) = _fixes(make_project, files)
    assert (fix.action, fix.reason) == (LeakAction.NO_FIX, LeakNoFix.CYCLE)


def test_a_lazy_facade_import_of_the_consumer_is_not_a_cycle(make_project) -> None:
    files = {
        "lib/__init__.py": (
            "from lib.core.logger import Logger\n\n\n"
            "def late():\n    import app.a\n\n    return app.a\n"
        ),
        "app/a.py": "from lib.core.logger import Logger\n",
    }
    (fix,) = _fixes(make_project, files)
    assert fix.action is LeakAction.FACADE_IMPORT


def test_a_module_import_gets_no_fix(make_project) -> None:
    (fix,) = _fixes(make_project, {"app/a.py": "import lib._private\n"})
    assert (fix.action, fix.reason, fix.symbol) == (
        LeakAction.NO_FIX,
        LeakNoFix.MODULE_IMPORT,
        None,
    )


def test_a_private_module_with_a_public_ancestor_facade_gets_the_facade_import(
    make_project,
) -> None:
    files = {
        "lib/_logging.py": "def log():\n    return 1\n",
        "lib/__init__.py": "from lib._logging import log\n",
        "app/a.py": "from lib._logging import log\n",
    }
    root = make_project({**LIB, **files})
    (leak,) = analyzed(root).leaks
    assert leak.kind is LeakKind.INTERNAL
    assert [(f.action, f.facade) for f in leak.fixes] == [(LeakAction.FACADE_IMPORT, "lib")]


@pytest.mark.parametrize("statement", ["from lib import log\n", "from lib import log as shown\n"])
def test_a_statement_that_goes_through_the_facade_is_never_reported(
    make_project, statement
) -> None:
    files = {
        "lib/_logging.py": "def log():\n    return 1\n",
        "lib/__init__.py": "from lib._logging import log\n",
        "app/a.py": statement,
    }
    root = make_project({**LIB, **files})
    assert analyzed(root).leaks == []
