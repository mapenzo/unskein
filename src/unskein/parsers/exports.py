"""Find the names a module exposes to ``from module import *``."""

import ast
from collections.abc import Iterator
from dataclasses import dataclass

ALL_NAME = "__all__"
PRIVATE_PREFIX = "_"
# Blocks of compound statements whose bindings still land in the module namespace.
MODULE_LEVEL_BLOCKS = ("body", "orelse", "handlers", "finalbody")
DEFINITION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@dataclass(frozen=True, slots=True)
class ModuleExports:
    """What ``from module import *`` brings in.

    Attributes:
        names: Exposed names, sorted.
        declares_all: Whether they come from a literal ``__all__``.
        bound_names: Every name the module binds at module level (private ones and
            names left out of ``__all__`` included), sorted.
    """

    names: tuple[str, ...]
    declares_all: bool
    bound_names: tuple[str, ...] = ()


def _module_level_statements(tree: ast.Module) -> Iterator[ast.stmt]:
    """Yield the statements whose bindings land in the module namespace.

    Descends into ``if``/``try``/``with``/``for``/``while`` blocks, never into
    function or class bodies.

    Args:
        tree: Parsed module.

    Yields:
        Each module-level statement, in code order.
    """
    stack: list[ast.AST] = list(reversed(tree.body))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.ExceptHandler):
            stack.extend(reversed(node.body))
            continue
        yield node
        if isinstance(node, DEFINITION_NODES):
            continue
        for field_name in reversed(MODULE_LEVEL_BLOCKS):
            stack.extend(reversed(getattr(node, field_name, None) or []))


def _target_names(target: ast.expr) -> Iterator[str]:
    """Yield the plain names an assignment target binds.

    Args:
        target: Left side of an assignment.

    Yields:
        Each name, including those inside tuple or list unpacking.
    """
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            yield from _target_names(element)


def _bound_names(node: ast.stmt) -> Iterator[str]:
    """Yield the names a module-level statement binds.

    Args:
        node: A module-level statement.

    Yields:
        Each bound name; ``import a.b`` binds ``a`` and ``from x import *`` binds nothing here.
    """
    if isinstance(node, DEFINITION_NODES):
        yield node.name
    elif isinstance(node, ast.Assign):
        for target in node.targets:
            yield from _target_names(target)
    elif isinstance(node, ast.AnnAssign):
        yield from _target_names(node.target)
    elif isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.asname or alias.name.split(".")[0]
    elif isinstance(node, ast.ImportFrom):
        for alias in node.names:
            if alias.name != "*":
                yield alias.asname or alias.name


def _literal_strings(value: ast.expr) -> list[str] | None:
    """Return the strings of a literal list or tuple of strings.

    Args:
        value: Right side of an ``__all__`` assignment.

    Returns:
        The strings, or None when the value is not such a literal.
    """
    if not isinstance(value, (ast.List, ast.Tuple)):
        return None
    if not all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in value.elts):
        return None
    return [element.value for element in value.elts]


def _literal_all(statements: list[ast.stmt]) -> list[str] | None:
    """Return the module's ``__all__`` when every assignment to it is a literal.

    Args:
        statements: Module-level statements, in code order.

    Returns:
        The declared names, or None when there is no ``__all__`` or one is computed.
    """
    declared: list[str] | None = None
    for node in statements:
        if isinstance(node, ast.Assign) and any(
            ALL_NAME in _target_names(target) for target in node.targets
        ):
            declared = _literal_strings(node.value)
            if declared is None:
                return None
        elif (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == ALL_NAME
        ):
            extra = _literal_strings(node.value)
            if declared is None or extra is None:
                return None
            declared += extra
    return declared


def module_exports(tree: ast.Module) -> ModuleExports:
    """Compute the names ``from module import *`` brings in from a parsed module.

    A literal ``__all__`` wins; otherwise every public module-level name counts.

    Args:
        tree: Parsed module.

    Returns:
        The exposed names, sorted, whether they come from ``__all__``, and every bound name.
    """
    statements = list(_module_level_statements(tree))
    names = {name for node in statements for name in _bound_names(node)}
    bound = tuple(sorted(names))
    declared = _literal_all(statements)
    if declared is not None:
        return ModuleExports(tuple(sorted(set(declared))), True, bound)
    public = {name for name in names if not name.startswith(PRIVATE_PREFIX)}
    return ModuleExports(tuple(sorted(public)), False, bound)
