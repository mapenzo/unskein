"""Find the names a module exposes to ``from module import *``."""

import ast
from collections.abc import Iterator
from dataclasses import dataclass

ALL_NAME = "__all__"
PRIVATE_PREFIX = "_"
# Blocks of compound statements whose bindings still land in the module namespace.
MODULE_LEVEL_BLOCKS = ("body", "orelse", "handlers", "finalbody")
DEFINITION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

IMPORT_NODES = (ast.Import, ast.ImportFrom)


@dataclass(frozen=True, slots=True)
class ModuleExports:
    """What ``from module import *`` brings in.

    Attributes:
        names: Exposed names, sorted.
        declares_all: Whether they come from a literal ``__all__``.
        bound_names: Every name the module binds at module level (private ones and
            names left out of ``__all__`` included), sorted.
        defined_names: Those of them the module defines itself (``def``, ``class``,
            assignments), not through an import, sorted.
        has_dynamic_all: Whether ``__all__`` is computed or changed in a way that cannot be
            read (a non-literal value, a method call, a subscript, two assignments): what a
            star import brings is then unknown.
    """

    names: tuple[str, ...]
    declares_all: bool
    bound_names: tuple[str, ...] = ()
    defined_names: tuple[str, ...] = ()
    has_dynamic_all: bool = False


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


def _writes_all(node: ast.stmt) -> bool:
    """Tell whether a statement changes ``__all__`` other than by a literal ``=`` or ``+=``.

    Args:
        node: A module-level statement.

    Returns:
        True for a method call on it (``.append``, ``.insert``…) or a subscript assignment.
    """
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        func = node.value.func
        return (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == ALL_NAME
        )
    if isinstance(node, (ast.Assign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return any(
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and target.value.id == ALL_NAME
            for target in targets
        )
    return False


def _has_dynamic_all(statements: list[ast.stmt], declared: list[str] | None) -> bool:
    """Tell whether the module's ``__all__`` cannot be read from its source.

    Args:
        statements: Module-level statements, in code order.
        declared: The literal ``__all__``, or None when there is none or it is computed.

    Returns:
        True when ``__all__`` is assigned more than once (which one runs may depend on a
        branch), assigned or changed by something that is not a literal, or changed
        through a method or a subscript.
    """
    assignments = 0
    for node in statements:
        if _writes_all(node):
            return True
        if isinstance(node, ast.Assign):
            assignments += any(ALL_NAME in _target_names(target) for target in node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            is_all = isinstance(node.target, ast.Name) and node.target.id == ALL_NAME
            assignments += is_all and isinstance(node, ast.AnnAssign)
            if is_all and declared is None:
                return True
    return assignments > 1 or (assignments == 1 and declared is None)


def module_exports(tree: ast.Module) -> ModuleExports:
    """Compute the names ``from module import *`` brings in from a parsed module.

    A literal ``__all__`` wins; otherwise every public module-level name counts.

    Args:
        tree: Parsed module.

    Returns:
        The exposed names, sorted, whether they come from ``__all__``, every bound name, the
        names it defines itself and whether ``__all__`` is dynamic.
    """
    statements = list(_module_level_statements(tree))
    names = {name for node in statements for name in _bound_names(node)}
    bound = tuple(sorted(names))
    defined = tuple(
        sorted(
            {
                name
                for node in statements
                if not isinstance(node, IMPORT_NODES)
                for name in _bound_names(node)
            }
        )
    )
    declared = _literal_all(statements)
    dynamic = _has_dynamic_all(statements, declared)
    if declared is not None:
        return ModuleExports(tuple(sorted(set(declared))), True, bound, defined, dynamic)
    public = {name for name in names if not name.startswith(PRIVATE_PREFIX)}
    return ModuleExports(tuple(sorted(public)), False, bound, defined, dynamic)


def _module_level_reads(tree: ast.Module) -> Iterator[ast.AST]:
    """Yield the nodes that run while the module is imported, function bodies excluded.

    Decorators, default values and annotations of a function run at import time; its body
    does not. Class bodies do run.

    Args:
        tree: Parsed module.

    Yields:
        Every such node.
    """
    stack: list[ast.AST] = list(tree.body)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack.extend(node.decorator_list)
            stack.append(node.args)
            if node.returns is not None:
                stack.append(node.returns)
        elif not isinstance(node, ast.Lambda):
            stack.extend(ast.iter_child_nodes(node))


def shadowed_after(tree: ast.Module, line: int) -> tuple[str, ...]:
    """Return the names the module rebinds for good after a line, unread before that.

    A top-level statement after the last star import that binds a name hides the star's
    one for good, unless code that runs at import time reads it first. Only direct
    statements of the module count (not ones inside ``if`` or ``try``), so the binding
    always runs.

    Args:
        tree: Parsed module.
        line: Line of the module's last star import.

    Returns:
        The hidden names, sorted.
    """
    bound_until: dict[str, int] = {}
    for node in tree.body:
        if node.lineno > line:
            for name in _bound_names(node):
                bound_until.setdefault(name, node.end_lineno or node.lineno)
    if not bound_until:
        return ()
    read_first: set[str] = set()
    for node in _module_level_reads(tree):
        name = None
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Load, ast.Del)):
            name = node.id
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        if name in bound_until and node.lineno <= bound_until[name]:
            read_first.add(name)
    return tuple(sorted(set(bound_until) - read_first))
