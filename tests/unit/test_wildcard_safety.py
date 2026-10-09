import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pathspec
import pytest
from wildcard_scenarios import REVIEW_SCENARIOS

from unskein.config import AnalysisConfig
from unskein.graph.metrics import AnalysisResult, analyze
from unskein.graph.stars import WildcardAction
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import WarningCode
from unskein.parsers.python_parser import PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]

SCENARIOS = {
    "unknown_star_upstream": (
        {
            "app/b.py": "BNAME = 'b'\n",
            "app/dyn.py": "__all__ = [n for n in ['D']]\nD = 1\n",
            "app/mid.py": "from app.b import *\nfrom app.dyn import *\n",
            "app/top.py": "from app.mid import *\nprint(BNAME)\n",
        },
        "import app.top",
    ),
    "attribute_through_a_module_import": (
        {
            "app/b.py": "W = 'b.W'\n",
            "app/m.py": "from app.b import *\n",
            "app/usem.py": "import app.m\nfrom app import m as mm\nprint(app.m.W, mm.W)\n",
        },
        "import app.usem",
    ),
    "rebound_after_the_star": (
        {
            "app/b.py": "X = 'b.X'\n",
            "app/late.py": "from app.b import *\nprint(X)\nX = 'late'\n",
        },
        "import app.late",
    ),
    "augmented_assignment": (
        {
            "app/b.py": "counter = 0\n",
            "app/aug.py": "from app.b import *\ncounter += 1\nprint(counter)\n",
        },
        "import app.aug",
    ),
    "deleted_name": (
        {"app/b.py": "Z = 1\n", "app/dl.py": "from app.b import *\ndel Z\nprint('ok')\n"},
        "import app.dl",
    ),
    "bound_before_the_star": (
        {
            "app/b.py": "Y = 'b.Y'\n",
            "app/early.py": "Y = 'mine'\nfrom app.b import *\nprint(Y)\n",
        },
        "import app.early",
    ),
    "alternative_branches": (
        {
            "app/fast.py": "V = 'fast'\n",
            "app/b.py": "V = 'b'\n",
            "app/alt.py": (
                "try:\n    from app.fast import *\nexcept ImportError:\n"
                "    from app.b import *\nprint(V)\n"
            ),
        },
        "import app.alt",
    ),
    "submodule_of_a_package": (
        {
            "app/pkg/__init__.py": "from .sub import f\n",
            "app/pkg/sub.py": "def f():\n    return 'f'\n",
            "app/user.py": "from app.pkg import *\nprint(sub.f(), f())\n",
        },
        "import app.user",
    ),
    "re_export_to_another_module": (
        {
            "app/types.py": "Config = 'config'\nOther = 1\n",
            "app/relay.py": "from app.types import *\n",
            "app/handler.py": "from app.relay import Config\nprint(Config)\n",
        },
        "import app.handler",
    ),
    "same_import_before_the_star": (
        {
            "app/b.py": "from typing import Final\nB = 1\n",
            "app/m.py": "from typing import Final\nfrom app.b import *\nX: Final = 1\nprint(X)\n",
        },
        "import app.m",
    ),
    "aliased_import_before_the_star": (
        {
            "app/b.py": "from typing import Final\n",
            "app/m.py": "from typing import Final as F\nfrom app.b import *\nprint(Final, F)\n",
        },
        "import app.m",
    ),
    "explicit_import_from_the_star_module_first": (
        {
            "app/b.py": "Params = 'params'\n",
            "app/m.py": "from app.b import Params\nfrom app.b import *\nprint(Params)\n",
        },
        "import app.m",
    ),
    "public_api_through_a_facade": (
        {
            "app/__init__.py": "from app.api import *\n",
            "app/types.py": "A = 1\nC = 3\n",
            "app/api.py": "from app.types import *\n\n\ndef total():\n    return A\n",
        },
        "import app; print(app.C, app.total())",
    ),
    "cycle_of_stars": (
        {
            "app/a.py": "from app.b import *\nX = 1\n",
            "app/b.py": "from app.a import *\nY = 2\n",
            "app/c.py": "from app.a import *\nprint(Y)\n",
        },
        "import app.c",
    ),
}


def _analyzed(root: Path) -> AnalysisResult:
    """Discover, parse, resolve and analyze a project."""
    adapter = PythonAdapter(AnalysisConfig(star_fixes=True))
    files = sorted(adapter.discover_files(root, pathspec.PathSpec([])))
    return analyze(resolve_indirection(adapter.parse(files, root)))


def _apply(root: Path, result: AnalysisResult) -> None:
    """Rewrite every star import the report fixes, exactly as the report says."""
    for wildcard in result.wildcards:
        for fix in wildcard.fixes:
            if fix.action is WildcardAction.NO_FIX:
                continue
            relative, line = fix.location.rsplit(":", 1)
            path = root / relative
            lines = path.read_text().splitlines(keepends=True)
            index = int(line) - 1
            indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
            if fix.action is WildcardAction.EXPLICIT:
                lines[index] = f"{indent}from {wildcard.name} import {', '.join(fix.names)}\n"
            else:
                lines[index] = f"{indent}pass\n"
            path.write_text("".join(lines))


def _run(root: Path, code: str) -> tuple[int, str]:
    """Run Python code in the project directory and return its exit code and output."""
    done = subprocess.run(
        [sys.executable, "-I", "-B", "-c", f"import sys; sys.path.insert(0, '.'); {code}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, done.stdout


@pytest.mark.parametrize("name", [*SCENARIOS, *REVIEW_SCENARIOS])
def test_applying_the_fixes_keeps_the_behavior(make_project: MakeProject, name: str) -> None:
    files, entry = {**SCENARIOS, **REVIEW_SCENARIOS}[name]
    root = make_project({"app/__init__.py": "", **files})
    before = _run(root, entry)
    assert before[0] == 0
    _apply(root, _analyzed(root))
    assert _run(root, entry) == before


def test_a_star_whose_names_are_unknown_further_up_warns(make_project: MakeProject) -> None:
    files, _ = SCENARIOS["unknown_star_upstream"]
    root = make_project({"app/__init__.py": "", **files})
    adapter = PythonAdapter(AnalysisConfig(star_fixes=True))
    parsed = adapter.parse(sorted(adapter.discover_files(root, pathspec.PathSpec([]))), root)
    stars = {
        (w.path.name, w.line)
        for w in resolve_indirection(parsed).warnings
        if w.code is WarningCode.STAR_IMPORT
    }
    assert stars == {("mid.py", 2), ("top.py", 1)}


def test_a_name_both_modules_import_the_same_way_is_kept_explicitly(
    make_project: MakeProject,
) -> None:
    files, _ = SCENARIOS["same_import_before_the_star"]
    root = make_project({"app/__init__.py": "", **files})
    (wildcard,) = _analyzed(root).wildcards
    assert [fix.action for fix in wildcard.fixes] == [WildcardAction.EXPLICIT]


def test_a_name_imported_from_the_star_module_itself_is_kept_explicitly(
    make_project: MakeProject,
) -> None:
    files, _ = SCENARIOS["explicit_import_from_the_star_module_first"]
    root = make_project({"app/__init__.py": "", **files})
    (wildcard,) = _analyzed(root).wildcards
    assert [fix.action for fix in wildcard.fixes] == [WildcardAction.EXPLICIT]
