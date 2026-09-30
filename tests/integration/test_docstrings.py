import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCUMENTED_DIRS = ("src", "scripts")

Definition = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def find_missing_docstrings(files: list[Path]) -> list[str]:
    """Return ``path:line name`` for every module, class or function lacking a docstring.

    Unlike ruff's pydocstyle rules, private names are checked too; ``__init__`` is
    exempt because constructor arguments are documented in the class docstring.

    Args:
        files: Python source files to inspect.

    Returns:
        One entry per undocumented definition, empty when everything is documented.
    """
    missing = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if ast.get_docstring(tree) is None:
            missing.append(f"{path}:1 <module>")
        for node in ast.walk(tree):
            if (
                isinstance(node, Definition)
                and node.name != "__init__"
                and ast.get_docstring(node) is None
            ):
                missing.append(f"{path}:{node.lineno} {node.name}")
    return missing


def test_checker_flags_private_and_module_level_gaps(tmp_path: Path) -> None:
    source = tmp_path / "mod.py"
    source.write_text('"""Doc."""\n\ndef _helper():\n    pass\n\nclass _Box:\n    """Doc."""\n')
    assert find_missing_docstrings([source]) == [f"{source}:3 _helper"]


def test_every_definition_in_src_and_scripts_has_a_docstring() -> None:
    files = sorted(p for d in DOCUMENTED_DIRS for p in (REPO_ROOT / d).rglob("*.py"))
    assert find_missing_docstrings(files) == []
