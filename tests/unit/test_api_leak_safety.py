import ast
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest
from api_scenarios import SCENARIOS
from test_api_leaks import analyzed

from unskein.graph.leaks import LeakAction, LeakFix, LeakModule


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


def _statements(leaks: list[LeakModule]) -> dict[tuple[str, int, str], list[LeakFix]]:
    """Group the proven fixes by (file, line, written module)."""
    grouped: dict[tuple[str, int, str], list[LeakFix]] = defaultdict(list)
    for leak in leaks:
        for fix in leak.fixes:
            if fix.action is LeakAction.FACADE_IMPORT:
                relative, line = fix.location.rsplit(":", 1)
                grouped[(relative, int(line), leak.name)].append(fix)
    return grouped


def _apply(root: Path, leaks: list[LeakModule]) -> None:
    """Rewrite every statement the report fixes, exactly as the report says."""
    by_file: dict[str, list[tuple[int, str, list[LeakFix]]]] = defaultdict(list)
    for (relative, line, module), fixes in _statements(leaks).items():
        by_file[relative].append((line, module, fixes))
    for relative, entries in by_file.items():
        path = root / relative
        source = path.read_text()
        tree = ast.parse(source)
        lines = source.splitlines(keepends=True)
        for line, module, fixes in sorted(entries, key=lambda entry: entry[:2], reverse=True):
            node = next(
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.lineno == line and n.module == module
            )
            moved = {fix.symbol for fix in fixes}
            keep = [alias for alias in node.names if alias.name not in moved]
            statements = []
            if keep:
                statements.append(ast.ImportFrom(module=node.module, names=keep, level=0))
            for facade in sorted({fix.facade for fix in fixes}):
                names = [ast.alias(fix.symbol, fix.alias) for fix in fixes if fix.facade == facade]
                statements.append(ast.ImportFrom(module=facade, names=names, level=0))
            indent = " " * node.col_offset
            text = "".join(f"{indent}{ast.unparse(statement)}\n" for statement in statements)
            lines[node.lineno - 1 : node.end_lineno] = [text]
        path.write_text("".join(lines))


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_applying_the_fixes_keeps_the_behavior(make_project, name: str) -> None:
    files, entry = SCENARIOS[name]
    root = make_project({"app/__init__.py": "", **files})
    before = _run(root, entry)
    assert before[0] == 0, before
    _apply(root, analyzed(root).leaks)
    assert _run(root, entry) == before


@pytest.mark.parametrize(
    "name",
    [
        "simple_bypass",
        "alias",
        "partial_statement",
        "multiline_parenthesized",
        "inside_try",
        "private_module_with_public_facade",
    ],
)
def test_these_scenarios_have_a_fix_to_apply(make_project, name: str) -> None:
    files, _ = SCENARIOS[name]
    root = make_project({"app/__init__.py": "", **files})
    assert _statements(analyzed(root).leaks)


@pytest.mark.parametrize(
    "name",
    [
        "guarded_facade_gets_no_fix",
        "rebound_facade_gets_no_fix",
        "facade_importing_the_consumer",
        "facade_importing_the_consumer_entered_through_the_consumer",
        "facade_imports_the_consumer_before_binding_the_name",
    ],
)
def test_these_scenarios_have_no_fix(make_project, name: str) -> None:
    files, _ = SCENARIOS[name]
    root = make_project({"app/__init__.py": "", **files})
    assert not _statements(analyzed(root).leaks)
