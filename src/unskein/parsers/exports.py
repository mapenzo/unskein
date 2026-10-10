"""Find the names a module exposes to ``from module import *``."""

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass

ALL_NAME = "__all__"
PRIVATE_PREFIX = "_"
# Blocks of compound statements whose bindings still land in the module namespace.
MODULE_LEVEL_BLOCKS = ("body", "orelse", "handlers", "finalbody")
DEFINITION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

IMPORT_NODES = (ast.Import, ast.ImportFrom)
STAR = "*"
# Calls that can bind module names nobody can read from the source.
NAMESPACE_WRITERS = frozenset({"globals", "vars", "exec"})
# Patterns that bind their ``name`` in a ``match``.
CAPTURE_NODES = (ast.MatchAs, ast.MatchStar)
# Bodies whose bindings stay out of the module namespace.
SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
GLOBAL_STATEMENT = re.compile(r"^\s*global\s+([\w\s,]+)", re.MULTILINE)
GLOBAL_SEPARATOR = ","
GLOBAL_KEYWORD = "global "
NAMESPACE_WRITER_CALL = re.compile(r"\b(?:globals|vars|exec)\s*\(")
WALRUS = ":="
TRY_NODES = (ast.Try, ast.TryStar)


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


def module_surface(tree: ast.Module, source: str | None = None) -> tuple[tuple[str, ...], bool]:
    """Tell which names a star of the module may leave unbound, and whether it is knowable.

    Args:
        tree: Parsed module.
        source: Its text, which lets cheap checks skip walks; None walks anyway.

    Returns:
        The names a star of it may bring that may be unbound when it runs (bound only
        inside a block, by a walrus, a ``match``, ``except … as`` or a ``global`` in a
        function, only annotated, or deleted), sorted; and whether it brings names nobody
        can list (a star import inside a block, ``globals()``, ``vars()`` or ``exec``).
    """
    statements = list(_module_level_statements(tree))
    names = {name for node in statements for name in _bound_names(node)}
    declared = _literal_all(statements)
    loose, uncertain = _loose_bindings(tree, statements, source)
    if declared is not None:
        exposed = set(declared)
    else:
        exposed = {name for name in names | loose if not name.startswith(PRIVATE_PREFIX)}
    steady = _steady_names(tree, statements)
    return tuple(sorted(name for name in exposed if name not in steady)), uncertain


def _steady_names(tree: ast.Module, statements: list[ast.stmt]) -> set[str]:
    """Return the names the module always binds: direct statements, never deleted.

    Args:
        tree: Parsed module.
        statements: Its module-level statements.

    Returns:
        Names bound by a direct statement of the module (not inside a block), other than a
        bare annotation, and never deleted at module level.
    """
    steady = {
        name
        for node in tree.body
        if not (isinstance(node, ast.AnnAssign) and node.value is None)
        for name in _bound_names(node)
    }
    deleted = {
        target.id
        for node in statements
        if isinstance(node, ast.Delete)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    return steady - deleted


def _loose_bindings(
    tree: ast.Module, statements: list[ast.stmt], source: str | None
) -> tuple[set[str], bool]:
    """Find the module names bound in ways a star import cannot count on.

    Only module-level statements are visited (function and class bodies bind nothing in
    the module). Expressions are walked for walrus only when the source has ``:=``;
    ``global`` statements and namespace writers are found in the text.

    Args:
        tree: Parsed module.
        statements: Its module-level statements (see ``_module_level_statements``).
        source: Its text, to skip walks that cannot matter; None walks anyway.

    Returns:
        Names bound by ``for``/``with`` targets, walrus, ``match`` captures, ``except … as``
        and ``global`` declarations in functions; and whether the module has a star import
        inside a block or calls ``globals()``, ``vars()`` or ``exec``.
    """
    loose: set[str] = set()
    uncertain = False
    top = {id(node) for node in tree.body}
    for node in statements:
        if isinstance(node, ast.ImportFrom) and id(node) not in top:
            uncertain |= any(alias.name == STAR for alias in node.names)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            loose.update(_target_names(node.target))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    loose.update(_target_names(item.optional_vars))
        elif isinstance(node, TRY_NODES):
            loose.update(handler.name for handler in node.handlers if handler.name)
        elif isinstance(node, ast.Match):
            for case in node.cases:
                loose.update(
                    n.name
                    for n in ast.walk(case.pattern)
                    if isinstance(n, CAPTURE_NODES) and n.name
                )
    if source is None or WALRUS in source:
        for node in statements:
            if not isinstance(node, SCOPE_NODES):
                loose.update(
                    n.target.id
                    for n in ast.walk(node)
                    if isinstance(n, ast.NamedExpr) and isinstance(n.target, ast.Name)
                )
    if source is None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                loose.update(node.names)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                uncertain |= node.func.id in NAMESPACE_WRITERS
    else:
        # Text is enough here and far cheaper than walking every function body; a match in a
        # comment or a string only withholds a fix.
        if GLOBAL_KEYWORD in source:
            for match in GLOBAL_STATEMENT.finditer(source):
                loose.update(name.strip() for name in match.group(1).split(GLOBAL_SEPARATOR))
        if any(f"{writer}(" in source for writer in NAMESPACE_WRITERS):
            uncertain |= NAMESPACE_WRITER_CALL.search(source) is not None
    return loose, uncertain


@dataclass(frozen=True, slots=True)
class NameBinding:
    """Where a module binds one name at module level.

    Attributes:
        sites: Statements that bind, delete or loosely rebind it, blocks included (function
            and class bodies bind nothing in the module).
        plain_import: Whether a statement directly in the module body is a
            ``from x import name`` that keeps the name.
        renamed: Whether a statement directly in the body binds it from another name
            (``from x import other as name``).
        in_block: Whether some binding sits inside a block (``if``, ``try``, ``with``…).
        uncertain: Whether the module can bind names nobody can read (``globals()``,
            ``vars()``, ``exec`` or a star import inside a block).
    """

    sites: int
    plain_import: bool
    renamed: bool
    in_block: bool
    uncertain: bool


def name_binding(tree: ast.Module, name: str) -> NameBinding:
    """Describe every way a module binds one name at module level.

    Args:
        tree: Parsed module.
        name: The name to look for.

    Returns:
        Its binding sites; a ``for``/``with``/``except … as``/``match``/walrus/``global``
        binding counts as one site, and so does ``del name``.
    """
    statements = list(_module_level_statements(tree))
    top = {id(node) for node in tree.body}
    loose, uncertain = _loose_bindings(tree, statements, None)
    sites = 0
    plain_import = renamed = in_block = False
    for node in statements:
        count = sum(1 for bound in _bound_names(node) if bound == name)
        if isinstance(node, ast.Delete):
            count += sum(1 for t in node.targets if isinstance(t, ast.Name) and t.id == name)
        if not count:
            continue
        sites += count
        if id(node) not in top:
            in_block = True
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if (alias.asname or alias.name) == name:
                    plain_import |= alias.name == name
                    renamed |= alias.name != name
    if name in loose:
        sites += 1
    return NameBinding(sites, plain_import, renamed, in_block, uncertain)
