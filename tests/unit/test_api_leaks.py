from pathlib import Path

import pathspec
import pytest

from unskein.config import AnalysisConfig, ApiContract, FindingsConfig, OptionalRules
from unskein.graph.leaks import (
    ApiVerdict,
    LeakAction,
    LeakKind,
    LeakNoFix,
    LeakReason,
    classify_module,
)
from unskein.graph.metrics import AnalysisResult, analyze
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.python_parser import PythonAdapter

LIB = {
    "lib/__init__.py": "from lib.core.logger import Logger\n",
    "lib/core/__init__.py": "",
    "lib/core/logger.py": "class Logger:\n    pass\n\n\nclass Other:\n    pass\n",
    "lib/_private.py": "SECRET = 1\n",
    "lib/internal/__init__.py": "",
    "lib/internal/tool.py": "def tool():\n    return 1\n",
    "app/__init__.py": "",
}


def analyzed(root: Path, api: ApiContract | None = None) -> AnalysisResult:
    """Parse, resolve and analyze a project with the API leak rule on."""
    api = api or ApiContract()
    adapter = PythonAdapter(AnalysisConfig(optional_rules=OptionalRules(api_leaks=True)))
    files = sorted(adapter.discover_files(root, pathspec.PathSpec([])))
    resolved = resolve_indirection(adapter.parse(files, root))
    return analyze(resolved, FindingsConfig(api=api))


@pytest.mark.parametrize(
    ("module", "verdict"),
    [
        ("lib.core.logger", ApiVerdict.PUBLIC),
        ("lib._private", ApiVerdict.CONVENTION_INTERNAL),
        ("lib.core._x.y", ApiVerdict.CONVENTION_INTERNAL),
        ("lib.__init__", ApiVerdict.PUBLIC),
        ("lib.internal.tool", ApiVerdict.DECLARED_INTERNAL),
        ("lib.internal.contracts", ApiVerdict.DECLARED_PUBLIC),
        ("lib.internalx", ApiVerdict.PUBLIC),
    ],
)
def test_the_longest_declared_prefix_decides_a_module(module: str, verdict: ApiVerdict) -> None:
    api = ApiContract(public=("lib.internal.contracts",), internal=("lib.internal",))
    assert classify_module(module, api) is verdict


def test_a_declared_public_prefix_beats_the_naming_convention() -> None:
    api = ApiContract(public=("lib._private",))
    assert classify_module("lib._private.sub", api) is ApiVerdict.DECLARED_PUBLIC


def test_bypassing_the_facade_is_a_bypass_leak(make_project) -> None:
    root = make_project({**LIB, "app/a.py": "from lib.core.logger import Logger\n"})
    (leak,) = analyzed(root).leaks
    assert (leak.name, leak.kind, leak.reason) == (
        "lib.core.logger",
        LeakKind.BYPASS,
        LeakReason.FACADE,
    )
    assert (leak.consumers, leak.roots) == (1, (("app", 1),))


def test_importing_through_the_facade_is_not_a_leak(make_project) -> None:
    root = make_project({**LIB, "app/a.py": "from lib import Logger\n"})
    assert analyzed(root).leaks == []


def test_a_private_module_is_an_internal_leak_by_convention(make_project) -> None:
    root = make_project({**LIB, "app/a.py": "from lib._private import SECRET\n"})
    (leak,) = analyzed(root).leaks
    assert (leak.kind, leak.reason) == (LeakKind.INTERNAL, LeakReason.CONVENTION)
    (fix,) = leak.fixes
    assert (fix.action, fix.reason) == (LeakAction.NO_FIX, LeakNoFix.NO_PUBLIC_PATH)
    assert fix.location == "app/a.py:1"


def test_a_private_name_from_a_public_module_is_not_a_leak(make_project) -> None:
    files = {
        **LIB,
        "lib/core/util.py": "_helper = 1\n",
        "app/a.py": "from lib.core.util import _helper\n",
    }
    assert analyzed(make_project(files)).leaks == []


def test_a_declared_internal_prefix_marks_its_modules(make_project) -> None:
    root = make_project({**LIB, "app/a.py": "from lib.internal.tool import tool\n"})
    (leak,) = analyzed(root, ApiContract(internal=("lib.internal",))).leaks
    assert (leak.name, leak.kind, leak.reason) == (
        "lib.internal.tool",
        LeakKind.INTERNAL,
        LeakReason.DECLARED,
    )


def test_a_declared_public_module_inside_an_internal_prefix_is_left_alone(make_project) -> None:
    root = make_project({**LIB, "app/a.py": "from lib.internal.tool import tool\n"})
    api = ApiContract(public=("lib.internal.tool",), internal=("lib.internal",))
    assert analyzed(root, api).leaks == []


def test_imports_inside_the_package_root_are_not_leaks(make_project) -> None:
    root = make_project({**LIB, "lib/core/user.py": "from lib._private import SECRET\n"})
    assert analyzed(root).leaks == []


def test_consumers_and_roots_are_counted(make_project) -> None:
    files = {
        **LIB,
        "app/a.py": "from lib._private import SECRET\nfrom lib._private import SECRET as S\n",
        "app/b.py": "from lib._private import SECRET\n",
        "tools/__init__.py": "",
        "tools/c.py": "from lib._private import SECRET\n",
    }
    (leak,) = analyzed(make_project(files)).leaks
    assert leak.consumers == 3
    assert leak.roots == (("app", 3), ("tools", 1))
    assert len(leak.fixes) == 4


def test_internal_leaks_come_first_then_the_most_consumed(make_project) -> None:
    files = {
        **LIB,
        "app/a.py": "from lib.core.logger import Logger\nfrom lib._private import SECRET\n",
        "app/b.py": "from lib.core.logger import Logger\n",
    }
    names = [leak.name for leak in analyzed(make_project(files)).leaks]
    assert names == ["lib._private", "lib.core.logger"]


def test_with_the_option_off_there_are_no_leaks(make_project) -> None:
    root = make_project({**LIB, "app/a.py": "from lib._private import SECRET\n"})
    adapter = PythonAdapter(AnalysisConfig())
    files = sorted(adapter.discover_files(root, pathspec.PathSpec([])))
    result = analyze(resolve_indirection(adapter.parse(files, root)))
    assert result.leaks == []
