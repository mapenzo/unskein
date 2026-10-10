"""Rewrite a module's source to move imports into functions or under TYPE_CHECKING."""

import ast
import io
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from unskein.parsers.exports import name_binding
from unskein.parsers.usage import postpones_annotations

INDENT = " " * 4
ALL_NAME = "__all__"
TYPE_CHECKING_NAME = "TYPE_CHECKING"
TYPING_MODULES = frozenset({"typing", "typing_extensions"})
TYPING_IMPORT = f"from typing import {TYPE_CHECKING_NAME}"
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
COMMENT_START = "#"
STAR = "*"
NAMESPACE_WRITERS = frozenset({"globals", "exec"})
VARS_NAME = "vars"
MODULE_NAME_VARIABLE = "__name__"
MODULES_ATTRIBUTE = "modules"


class RewriteRefusal(StrEnum):
    """Why a move was not applied; each value equals the same-named ``ProofReason``.

    Attributes:
        NESTED_IMPORT: The import is not at module level.
        MULTIPLE_STATEMENTS: The import shares its line with another statement.
        STAR_IMPORT: The statement is ``from x import *``.
        ANNOTATIONS_EVALUATED: The names are read in annotations that run at import.
        READ_AT_IMPORT: The names are read while the module is being imported.
        READ_AT_RUNTIME: The names are read in code that a ``TYPE_CHECKING`` guard hides.
        NO_READER: No function reads the imported names.
        NAME_REUSED: The name is bound again, or a reading function binds it.
        EXPORTED: The name is listed in ``__all__``.
        INLINE_BODY: The first statement of a reading function shares its line.
        UNREADABLE: The lines do not match an import, or the result would not parse.
    """

    NESTED_IMPORT = "nested_import"
    MULTIPLE_STATEMENTS = "multiple_statements"
    STAR_IMPORT = "star_import"
    ANNOTATIONS_EVALUATED = "annotations_evaluated"
    READ_AT_IMPORT = "read_at_import"
    READ_AT_RUNTIME = "read_at_runtime"
    NO_READER = "no_reader"
    NAME_REUSED = "name_reused"
    EXPORTED = "exported"
    INLINE_BODY = "inline_body"
    UNREADABLE = "unreadable"


class MoveKind(StrEnum):
    """Where an import statement goes.

    Attributes:
        LAZY: Into each function that reads its names.
        TYPE_CHECKING: Under ``if TYPE_CHECKING:`` at the same place.
    """

    LAZY = "lazy"
    TYPE_CHECKING = "type_checking"


@dataclass(frozen=True, slots=True)
class Move:
    """One import move to apply.

    Attributes:
        kind: Where the import goes.
        lines: Line numbers (1-based) of the import statements to move.
    """

    kind: MoveKind
    lines: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Rewritten:
    """The outcome of applying some moves to a module.

    Attributes:
        source: The new text; the original one when nothing was applied.
        refusals: Per move, why it was refused, or None when it was applied.
    """

    source: str
    refusals: tuple[RewriteRefusal | None, ...]


@dataclass(frozen=True, slots=True)
class _Edit:
    """Replace the lines ``start:stop`` (0-based, stop exclusive) of a module by new ones.

    Attributes:
        start: Index of the first replaced line.
        stop: Index after the last replaced line; equal to ``start`` for an insertion.
        lines: The new lines, each with its line ending.
    """

    start: int
    stop: int
    lines: tuple[str, ...]


@dataclass(slots=True)
class _Context:
    """What planning a move needs to know about one module.

    Mutable on purpose: planning the first ``TYPE_CHECKING`` move records that the
    ``typing`` import was added so later moves of the file do not repeat it.

    Attributes:
        tree: Parsed module.
        text_lines: Source lines with their endings, split like ``ast`` counts them.
        newline: Line ending to use for new lines.
        postponed: Whether the module has ``from __future__ import annotations``.
        typing_import_added: Whether an accepted move already adds the ``typing`` import.
    """

    tree: ast.Module
    text_lines: list[str]
    newline: str
    postponed: bool
    typing_import_added: bool = False


@dataclass(slots=True)
class _Reads:
    """Where a module reads some names, as far as moving their import is concerned.

    Attributes:
        at_import: A read that runs while the module is imported.
        in_function: A read inside a function or lambda body.
        evaluated_annotation: An annotation that runs at import and mentions a name.
        in_annotation: An annotation that never runs (postponed, quoted or local).
        import_names: Every name and attribute loaded while the module is imported, which
            is how a function defined here can run before the import cut matters.
    """

    at_import: bool = False
    in_function: bool = False
    evaluated_annotation: bool = False
    in_annotation: bool = False
    import_names: set[str] = field(default_factory=set)


def _split_lines(source: str) -> list[str]:
    """Split a text into lines that keep their endings, as ``ast`` counts them.

    Args:
        source: The module's text.

    Returns:
        The lines; a line feed, a carriage return or both end each one.
    """
    return io.StringIO(source, newline="").readlines()


def _newline_of(text_lines: Sequence[str]) -> str:
    """Return the line ending of the first terminated line, or a line feed when none has one.

    Args:
        text_lines: Source lines with their endings.

    Returns:
        The line ending to use for new lines.
    """
    for line in text_lines:
        stripped = line.rstrip("\r\n")
        if stripped != line:
            return line[len(stripped) :]
    return "\n"


def _apply(source: str, edits: Sequence[_Edit]) -> str:
    """Apply every edit against the original line numbers.

    Edits are applied from the last line backwards so earlier line numbers stay valid;
    insertions at the same line keep their order.

    Args:
        source: The original text.
        edits: Edits expressed in original line numbers.

    Returns:
        The edited text.
    """
    lines = _split_lines(source)
    ordered = sorted(enumerate(edits), key=lambda item: (item[1].start, item[0]), reverse=True)
    for _, edit in ordered:
        lines[edit.start : edit.stop] = edit.lines
    return "".join(lines)


def _prefix(text_line: str, column: int) -> str:
    """Return the text of a line before a UTF-8 byte column, as ``ast`` measures it.

    Args:
        text_line: A source line.
        column: Byte offset in its UTF-8 encoding.

    Returns:
        The text before that column.
    """
    return text_line.encode()[:column].decode(errors="replace")


def _suffix(text_line: str, column: int) -> str:
    """Return the text of a line from a UTF-8 byte column on.

    Args:
        text_line: A source line.
        column: Byte offset in its UTF-8 encoding.

    Returns:
        The text from that column.
    """
    return text_line.encode()[column:].decode(errors="replace")


def _alone(text_lines: Sequence[str], node: ast.stmt) -> bool:
    """Tell whether a statement owns its lines, apart from indentation and a comment.

    Args:
        text_lines: Source lines with their endings.
        node: The statement.

    Returns:
        False when another statement shares a line with it (``a; b``, a trailing ``;``).
    """
    end_line = node.end_lineno or node.lineno
    before = _prefix(text_lines[node.lineno - 1], node.col_offset)
    after = _suffix(text_lines[end_line - 1], node.end_col_offset or 0).strip()
    return not before.strip() and (not after or after.startswith(COMMENT_START))


def _statement_lines(ctx: _Context, node: ast.stmt) -> list[str]:
    """Return the lines of a statement, the last one with a line ending.

    Args:
        ctx: The module being rewritten.
        node: The statement.

    Returns:
        Its source lines, unchanged.
    """
    lines = ctx.text_lines[node.lineno - 1 : node.end_lineno or node.lineno]
    if lines and lines[-1] == lines[-1].rstrip("\r\n"):
        lines[-1] += ctx.newline
    return lines


def _locate(
    ctx: _Context, lines: Collection[int]
) -> list[ast.Import | ast.ImportFrom] | RewriteRefusal:
    """Find the import statements that start on the given lines.

    Args:
        ctx: The module being rewritten.
        lines: Wanted line numbers.

    Returns:
        The statements, or why they cannot be moved.
    """
    wanted = set(lines)
    found = [
        node
        for node in ast.walk(ctx.tree)
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node.lineno in wanted
    ]
    if not found or {node.lineno for node in found} != wanted:
        return RewriteRefusal.UNREADABLE
    top = {id(node) for node in ctx.tree.body}
    if any(id(node) not in top for node in found):
        return RewriteRefusal.NESTED_IMPORT
    found.sort(key=lambda node: node.lineno)
    for node in found:
        if isinstance(node, ast.ImportFrom) and any(alias.name == STAR for alias in node.names):
            return RewriteRefusal.STAR_IMPORT
    if not all(_alone(ctx.text_lines, node) for node in found):
        return RewriteRefusal.MULTIPLE_STATEMENTS
    return found


def _bound_names(statements: Sequence[ast.Import | ast.ImportFrom]) -> frozenset[str]:
    """Return the names that some import statements bind.

    Args:
        statements: Import statements.

    Returns:
        The bound names (``import a.b`` binds ``a``).
    """
    names: set[str] = set()
    for node in statements:
        for alias in node.names:
            if isinstance(node, ast.Import):
                names.add(alias.asname or alias.name.split(".")[0])
            else:
                names.add(alias.asname or alias.name)
    return frozenset(names)


def _all_value(node: ast.stmt) -> ast.expr | None:
    """Return the value a statement assigns to ``__all__``, if it does.

    Args:
        node: A module-level statement.

    Returns:
        The assigned expression, or None for any other statement.
    """
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        targets = [node.target]
    else:
        return None
    if any(isinstance(target, ast.Name) and target.id == ALL_NAME for target in targets):
        return node.value
    return None


def _changes_all(node: ast.AST) -> bool:
    """Tell whether a node calls a method on ``__all__`` (``append``, ``extend``…).

    Args:
        node: Any node.

    Returns:
        True for ``__all__.<method>(...)``.
    """
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == ALL_NAME
    )


def _exported(tree: ast.Module, names: Collection[str]) -> bool:
    """Tell whether ``__all__`` lists any of the names, or cannot be read statically.

    Args:
        tree: Parsed module.
        names: Names to look for.

    Returns:
        True when a literal ``__all__`` mentions one of them, or when ``__all__`` is
        computed or changed by a method call (its content is then unknown).
    """
    if any(_changes_all(node) for node in ast.walk(tree)):
        return True
    for node in tree.body:
        value = _all_value(node)
        if value is None:
            continue
        if not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            return True
        if any(not isinstance(part, ast.Constant) or part.value in names for part in value.elts):
            return True
    return False


def _reaches_the_module(node: ast.expr) -> bool:
    """Tell whether an expression names the module itself or the table of loaded modules.

    Args:
        node: The argument of a ``vars`` call.

    Returns:
        True when ``__name__`` or ``sys.modules`` appears anywhere in it.
    """
    return any(
        (isinstance(part, ast.Name) and part.id == MODULE_NAME_VARIABLE)
        or (isinstance(part, ast.Attribute) and part.attr == MODULES_ATTRIBUTE)
        for part in ast.walk(node)
    )


def _writes_namespace(tree: ast.Module) -> bool:
    """Tell whether a call can bind module names that cannot be read from the source.

    ``globals()``, ``exec`` and ``vars()`` without arguments reach the module namespace;
    ``vars(obj)`` on another object does not, unless ``obj`` names the module itself. A
    module object kept in another variable is not followed.

    Args:
        tree: Parsed module.

    Returns:
        True when such a call exists anywhere in the module.
    """
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id in NAMESPACE_WRITERS:
            return True
        if node.func.id == VARS_NAME and (not node.args or _reaches_the_module(node.args[0])):
            return True
    return False


def _namespace_unreadable(tree: ast.Module) -> bool:
    """Tell whether the module can bind names nobody can read from its source.

    Args:
        tree: Parsed module.

    Returns:
        True for a star import inside a block or a call that writes the module namespace.
    """
    top = {id(node) for node in tree.body}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and id(node) not in top
            and any(alias.name == STAR for alias in node.names)
        ):
            return True
    return _writes_namespace(tree)


def _sibling_imports(
    tree: ast.Module, statements: Sequence[ast.Import | ast.ImportFrom], names: Collection[str]
) -> Counter[str]:
    """Count, per name, the other module-level ``import name.sub`` statements.

    ``import pkg.sub`` binds the same package object that ``import pkg`` binds, so it keeps
    the name alive when the plain import moves away.

    Args:
        tree: Parsed module.
        statements: The statements being moved; they are not siblings of themselves.
        names: Names the moved statements bind.

    Returns:
        How many such statements bind each name; a renamed one (``as``) does not count.
    """
    moved = {id(node) for node in statements}
    found: Counter[str] = Counter()
    for node in tree.body:
        if id(node) in moved or not isinstance(node, ast.Import):
            continue
        for alias in node.names:
            root, dot, _ = alias.name.partition(".")
            if dot and alias.asname is None and root in names:
                found[root] += 1
    return found


def _check_names(
    ctx: _Context, statements: Sequence[ast.Import | ast.ImportFrom], names: Collection[str]
) -> RewriteRefusal | None:
    """Refuse a move whose names are bound elsewhere or exported.

    A name may also be bound by sibling ``import name.sub`` statements, and a module is
    only uncertain when it can really write its namespace.

    Args:
        ctx: The module being rewritten.
        statements: The located statements being moved.
        names: Names the moved statements bind.

    Returns:
        Why the move is unsafe, or None.
    """
    moved = Counter(name for node in statements for name in _bound_names([node]))
    siblings = _sibling_imports(ctx.tree, statements, names)
    unreadable = _namespace_unreadable(ctx.tree)
    for name in names:
        binding = name_binding(ctx.tree, name)
        if binding.in_block or (binding.uncertain and unreadable):
            return RewriteRefusal.NAME_REUSED
        if moved[name] != 1 or binding.sites != 1 + siblings[name]:
            return RewriteRefusal.NAME_REUSED
    if _exported(ctx.tree, names):
        return RewriteRefusal.EXPORTED
    return None


# pylint: disable=invalid-name
class _ReadScanner(ast.NodeVisitor):
    """Classify every read of some names by when Python runs it.

    Attributes:
        names: The names to track.
        postponed: Whether the module postpones annotations.
        reads: What was found.
    """

    def __init__(self, names: Collection[str], *, postponed: bool) -> None:
        """Start a scan at module level.

        Args:
            names: The names to track.
            postponed: Whether the module postpones annotations.
        """
        self.names = names
        self.postponed = postponed
        self.reads = _Reads()
        self._in_function = False

    def _mentions(self, node: ast.AST) -> bool:
        """Tell whether a subtree reads one of the tracked names.

        Args:
            node: The subtree.

        Returns:
            True when a tracked name is loaded in it.
        """
        return any(
            isinstance(part, ast.Name) and part.id in self.names and isinstance(part.ctx, ast.Load)
            for part in ast.walk(node)
        )

    def _annotation(self, node: ast.expr | None, *, executed: bool) -> None:
        """Record a read inside an annotation according to when Python evaluates it.

        Args:
            node: The annotation, if any.
            executed: Whether Python evaluates it when its definition runs.
        """
        if node is None or not self._mentions(node):
            return
        if self.postponed or not executed:
            self.reads.in_annotation = True
        elif self._in_function:
            self.reads.in_function = True
        else:
            self.reads.evaluated_annotation = True

    def visit_Name(self, node: ast.Name) -> None:
        """Record a load of a tracked name in the current mode.

        Args:
            node: A name.
        """
        if not isinstance(node.ctx, ast.Load):
            return
        if not self._in_function:
            self.reads.import_names.add(node.id)
        if node.id in self.names:
            if self._in_function:
                self.reads.in_function = True
            else:
                self.reads.at_import = True

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Record an attribute loaded while the module is imported, then visit its value.

        Args:
            node: An attribute access.
        """
        if not self._in_function:
            self.reads.import_names.add(node.attr)
        self.generic_visit(node)

    def _visit_arguments(self, arguments: ast.arguments) -> None:
        """Visit defaults like any code and annotations by when they run.

        Args:
            arguments: The parameters of a function or lambda.
        """
        for default in [*arguments.defaults, *arguments.kw_defaults]:
            if default is not None:
                self.visit(default)
        every = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        every += [arg for arg in (arguments.vararg, arguments.kwarg) if arg is not None]
        for arg in every:
            self._annotation(arg.annotation, executed=True)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Visit what runs when the definition runs, then the body as function code.

        Args:
            node: A function definition.
        """
        for part in [*node.decorator_list, *node.type_params]:
            self.visit(part)
        self._visit_arguments(node.args)
        self._annotation(node.returns, executed=True)
        outer, self._in_function = self._in_function, True
        for statement in node.body:
            self.visit(statement)
        self._in_function = outer

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        """Visit the defaults as current code; a lambda outside any function counts as a read.

        A lambda defined at module or class level is not a function the move can reach, so
        a name read in its body must stay importable there.

        Args:
            node: A lambda.
        """
        self._visit_arguments(node.args)
        if not self._in_function:
            self.reads.at_import |= self._mentions(node.body)
            return
        self.visit(node.body)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Visit an annotated assignment; local annotations never run.

        Args:
            node: An annotated assignment.
        """
        self.visit(node.target)
        self._annotation(node.annotation, executed=not self._in_function)
        if node.value is not None:
            self.visit(node.value)


# pylint: enable=invalid-name


def _scan_reads(ctx: _Context, names: Collection[str], *, postpone: bool = False) -> _Reads:
    """Classify every read of the names in a module.

    Args:
        ctx: The module being rewritten.
        names: Names the moved statements bind.
        postpone: Whether the move adds ``from __future__ import annotations``, so annotations
            do not run.

    Returns:
        Where the module reads them.
    """
    scanner = _ReadScanner(names, postponed=ctx.postponed or postpone)
    scanner.visit(ctx.tree)
    return scanner.reads


def _reads_in_body(
    function: ast.FunctionDef | ast.AsyncFunctionDef, names: Collection[str]
) -> bool:
    """Tell whether the body of a function loads one of the names.

    Args:
        function: A function definition.
        names: Names to look for.

    Returns:
        True when some statement of the body, nested code included, loads one.
    """
    return any(
        isinstance(node, ast.Name) and node.id in names and isinstance(node.ctx, ast.Load)
        for statement in function.body
        for node in ast.walk(statement)
    )


def _outermost_readers(
    tree: ast.Module, names: Collection[str]
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """List the outermost functions whose body reads one of the names.

    Args:
        tree: Parsed module.
        names: Names to look for.

    Returns:
        The readers, so one import per reader covers every nested function too.
    """
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    def visit(node: ast.AST) -> None:
        """Collect readers below a node, without descending into a reader.

        Args:
            node: The node to search under.
        """
        for child in ast.iter_child_nodes(node):
            if isinstance(child, FUNCTIONS) and _reads_in_body(child, names):
                found.append(child)
            else:
                visit(child)

    visit(tree)
    return found


def _runs_at_import(
    tree: ast.Module, readers: Sequence[ast.FunctionDef | ast.AsyncFunctionDef], loaded: set[str]
) -> bool:
    """Tell whether some reader may run while the module loads.

    A reader runs at import when its name, or the name of a class that holds it, is loaded
    at module level (a call, an instantiation, a decorator). Calls through other functions
    are not followed.

    Args:
        tree: Parsed module.
        readers: The functions that read the moved names.
        loaded: Names and attributes loaded while the module is imported.

    Returns:
        True when a reader, or the class around it, is mentioned at import time.
    """
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    for reader in readers:
        labels = {reader.name}
        node: ast.AST | None = parents.get(reader)
        while node is not None:
            if isinstance(node, ast.ClassDef):
                labels.add(node.name)
            node = parents.get(node)
        if labels & loaded:
            return True
    return False


def _rebinds(scope: ast.AST, names: Collection[str], ignored: Collection[int] = ()) -> bool:
    """Tell whether a scope binds, deletes or declares any of the names.

    A new local import would be overwritten by (or conflict with) such a binding.

    Args:
        scope: A function, class or module.
        names: Names the moved import binds.
        ignored: ``id`` of the nodes that do not count.

    Returns:
        True when the scope reuses one of the names.
    """
    for node in ast.walk(scope):
        if id(node) in ignored:
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            hit = node.id in names
        elif isinstance(node, ast.arg):
            hit = node.arg in names
        elif isinstance(node, (*FUNCTIONS, ast.ClassDef)):
            hit = node.name in names
        elif isinstance(node, ast.alias):
            hit = (node.asname or node.name.split(".")[0]) in names
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            hit = any(name in names for name in node.names)
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
            hit = node.name in names
        elif isinstance(node, ast.MatchMapping):
            hit = node.rest in names
        else:
            hit = False
        if hit:
            return True
    return False


def _is_plain_alias(alias: ast.alias, names: Collection[str]) -> bool:
    """Tell whether an import alias binds one of the names without renaming it.

    Args:
        alias: An alias of an ``import`` statement.
        names: Names of interest.

    Returns:
        True for ``import name`` or ``import name.sub`` without ``as``.
    """
    return alias.asname is None and alias.name.split(".")[0] in names


def _own_imports(
    function: ast.FunctionDef | ast.AsyncFunctionDef, names: Collection[str]
) -> list[ast.Import]:
    """List the plain imports of the names written in the function itself.

    Args:
        function: A function definition.
        names: Names of interest.

    Returns:
        The statements, nested functions, classes and lambdas apart.
    """
    found: list[ast.Import] = []
    stack: list[ast.AST] = list(function.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (*FUNCTIONS, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Import) and any(_is_plain_alias(a, names) for a in node.names):
            found.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return found


def _imports_locally(
    function: ast.FunctionDef | ast.AsyncFunctionDef, names: Collection[str]
) -> bool:
    """Tell whether a function imports every name it reads before it reads it.

    Such a function does not depend on the module-level import, so the move leaves it alone.

    Args:
        function: A function definition.
        names: Names the moved import binds.

    Returns:
        True when every read of a name comes after the function's own plain import of it
        and the function binds the names in no other way.
    """
    firsts: dict[str, tuple[int, int]] = {}
    imports = _own_imports(function, names)
    for node in imports:
        end = (node.end_lineno or node.lineno, node.end_col_offset or 0)
        for alias in node.names:
            if _is_plain_alias(alias, names):
                root = alias.name.split(".")[0]
                firsts[root] = min(firsts.get(root, end), end)
    ignored = {id(part) for node in imports for part in (node, *node.names)}
    if not firsts or _rebinds(function, names, ignored):
        return False
    return all(
        node.id in firsts and (node.lineno, node.col_offset) >= firsts[node.id]
        for node in ast.walk(function)
        if isinstance(node, ast.Name) and node.id in names and isinstance(node.ctx, ast.Load)
    )


def _is_docstring(node: ast.stmt) -> bool:
    """Tell whether a statement is a string expression (a docstring when first).

    Args:
        node: A statement.

    Returns:
        True for a bare string literal.
    """
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _anchor(
    ctx: _Context, function: ast.FunctionDef | ast.AsyncFunctionDef
) -> tuple[int, str] | RewriteRefusal:
    """Find where a function's body begins, after its docstring.

    Args:
        ctx: The module being rewritten.
        function: A function definition.

    Returns:
        The 0-based line index of the first real statement and its indentation, or
        ``INLINE_BODY`` when that statement shares the ``def`` line.
    """
    body = function.body
    first = body[1] if len(body) > 1 and _is_docstring(body[0]) else body[0]
    line = min([first.lineno, *(d.lineno for d in getattr(first, "decorator_list", ()))])
    text = ctx.text_lines[line - 1]
    if line == first.lineno and _prefix(text, first.col_offset).strip():
        return RewriteRefusal.INLINE_BODY
    return line - 1, text[: len(text) - len(text.lstrip())]


def _indented(indent: str, line: str) -> str:
    """Indent a source line, leaving blank lines blank.

    Args:
        indent: Indentation to add.
        line: A source line with its ending.

    Returns:
        The indented line.
    """
    return indent + line if line.strip() else line


def _reader_edits(
    ctx: _Context,
    statements: Sequence[ast.Import | ast.ImportFrom],
    names: Collection[str],
    *,
    loaded: set[str],
) -> list[_Edit] | RewriteRefusal:
    """Plan inserting the statements into every function that needs them.

    A function that already imports the names itself is left alone.

    Args:
        ctx: The module being rewritten.
        statements: The located import statements.
        names: Names the statements bind.
        loaded: Names and attributes loaded while the module is imported.

    Returns:
        The insertions, or why the move is unsafe.
    """
    readers = _outermost_readers(ctx.tree, names)
    if not readers:
        return RewriteRefusal.NO_READER
    needy = [reader for reader in readers if not _imports_locally(reader, names)]
    if any(_rebinds(reader, names) for reader in needy):
        return RewriteRefusal.NAME_REUSED
    if _runs_at_import(ctx.tree, needy, loaded):
        return RewriteRefusal.READ_AT_IMPORT
    edits: list[_Edit] = []
    for reader in needy:
        anchor = _anchor(ctx, reader)
        if isinstance(anchor, RewriteRefusal):
            return anchor
        index, indent = anchor
        for node in statements:
            moved = tuple(_indented(indent, line) for line in _statement_lines(ctx, node))
            edits.append(_Edit(index, index, moved))
    return edits


def _plan_lazy(
    ctx: _Context,
    statements: Sequence[ast.Import | ast.ImportFrom],
    *,
    postpone: bool = False,
) -> list[_Edit] | RewriteRefusal:
    """Plan moving some imports into every outermost function that reads their names.

    Args:
        ctx: The module being rewritten.
        statements: The located import statements.
        postpone: Whether the move adds ``from __future__ import annotations``.

    Returns:
        The edits, or why the move is unsafe.
    """
    names = _bound_names(statements)
    refusal = _check_names(ctx, statements, names)
    if refusal is not None:
        return refusal
    reads = _scan_reads(ctx, names, postpone=postpone)
    if reads.at_import or reads.evaluated_annotation:
        return RewriteRefusal.READ_AT_IMPORT
    inserted = _reader_edits(ctx, statements, names, loaded=reads.import_names)
    if isinstance(inserted, RewriteRefusal):
        return inserted
    removals = [_Edit(node.lineno - 1, node.end_lineno or node.lineno, ()) for node in statements]
    return inserted + removals


def _typing_guard_available(ctx: _Context, before_line: int) -> bool:
    """Tell whether the module already binds ``TYPE_CHECKING`` from the typing modules.

    Args:
        ctx: The module being rewritten.
        before_line: The first line a guard would be written on; the binding must come first.

    Returns:
        True when one plain ``from typing import TYPE_CHECKING`` is its only binding.
    """
    binding = name_binding(ctx.tree, TYPE_CHECKING_NAME)
    if binding.sites != 1 or binding.in_block or binding.uncertain:
        return False
    return any(
        isinstance(node, ast.ImportFrom)
        and node.level == 0
        and node.module in TYPING_MODULES
        and node.lineno < before_line
        and any(alias.name == TYPE_CHECKING_NAME and alias.asname is None for alias in node.names)
        for node in ctx.tree.body
    )


def _plan_type_checking(
    ctx: _Context,
    statements: Sequence[ast.Import | ast.ImportFrom],
    *,
    postpone: bool = False,
) -> list[_Edit] | RewriteRefusal:
    """Plan moving some imports under ``if TYPE_CHECKING:`` where they are.

    Args:
        ctx: The module being rewritten.
        statements: The located import statements.
        postpone: Whether the move adds ``from __future__ import annotations``.

    Returns:
        The edits, or why the move is unsafe.
    """
    names = _bound_names(statements)
    refusal = _check_names(ctx, statements, names)
    if refusal is not None:
        return refusal
    reads = _scan_reads(ctx, names, postpone=postpone)
    if reads.evaluated_annotation:
        return RewriteRefusal.ANNOTATIONS_EVALUATED
    if reads.at_import or reads.in_function:
        return RewriteRefusal.READ_AT_RUNTIME
    unbound = name_binding(ctx.tree, TYPE_CHECKING_NAME).sites == 0
    if not unbound and not _typing_guard_available(ctx, statements[0].lineno):
        return RewriteRefusal.NAME_REUSED
    add_import = unbound and not ctx.typing_import_added
    edits: list[_Edit] = []
    for index, node in enumerate(statements):
        block = [f"if {TYPE_CHECKING_NAME}:{ctx.newline}"]
        block += [INDENT + line for line in _statement_lines(ctx, node)]
        if add_import and index == 0:
            block.insert(0, TYPING_IMPORT + ctx.newline)
        edits.append(_Edit(node.lineno - 1, node.end_lineno or node.lineno, tuple(block)))
    ctx.typing_import_added = ctx.typing_import_added or add_import
    return edits


def rewrite_source(source: str, moves: Sequence[Move]) -> Rewritten:
    """Apply some import moves to a module's source, all against the original tree.

    Args:
        source: The module's text.
        moves: Moves to apply; each names the lines of the import statements it moves.

    Returns:
        The new text and, per move, why it was refused (None when applied). A move that
        repeats an earlier one shares its outcome; one that overlaps another is refused.
        When the result does not parse, nothing is applied.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return Rewritten(source, (RewriteRefusal.UNREADABLE,) * len(moves))
    text_lines = _split_lines(source)
    ctx = _Context(tree, text_lines, _newline_of(text_lines), postpones_annotations(tree))
    outcomes: dict[tuple[MoveKind, tuple[int, ...]], RewriteRefusal | None] = {}
    claimed: set[int] = set()
    edits: list[_Edit] = []
    keys = [(move.kind, move.lines) for move in moves]
    for key in keys:
        if key in outcomes:
            continue
        kind, lines = key
        if claimed & set(lines):
            outcomes[key] = RewriteRefusal.MULTIPLE_STATEMENTS
            continue
        statements = _locate(ctx, lines)
        planner = _plan_lazy if kind is MoveKind.LAZY else _plan_type_checking
        planned = (
            planner(ctx, statements) if not isinstance(statements, RewriteRefusal) else statements
        )
        if isinstance(planned, RewriteRefusal):
            outcomes[key] = planned
            continue
        outcomes[key] = None
        edits.extend(planned)
        claimed.update(lines)
    if not edits:
        return Rewritten(source, tuple(outcomes[key] for key in keys))
    new = _apply(source, edits)
    try:
        ast.parse(new)
    except (SyntaxError, ValueError):
        return Rewritten(
            source,
            tuple(
                RewriteRefusal.UNREADABLE if outcomes[key] is None else outcomes[key]
                for key in keys
            ),
        )
    return Rewritten(new, tuple(outcomes[key] for key in keys))
