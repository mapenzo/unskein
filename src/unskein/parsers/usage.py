"""Find how a module uses the names its imports bind: attribute chains, contexts and evidence."""

import ast
import re
import warnings
from collections.abc import Collection
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from unskein.parsers.discovery import detect_encoding
from unskein.parsers.models import ImportKind, ModuleInfo


@dataclass(slots=True)
class NameUsage:
    """How a module uses one imported name.

    Attributes:
        chains: Dotted attribute chains read through the name, e.g. ``a.b.c`` for ``p.a.b.c``.
        escapes: Whether the name is used by itself (passed as a value, assigned, rebound)
            or written through, so the chains alone do not tell what the module depends on.
    """

    chains: set[str] = field(default_factory=set)
    escapes: bool = False


def _mentions(text: str, name: str) -> bool:
    """Tell whether a string is the name or reads an attribute of it.

    Args:
        text: String constant found in the module.
        name: Tracked name.

    Returns:
        True when ``text`` equals ``name`` or contains ``name.`` as a whole identifier.
    """
    return text == name or re.search(rf"(?<![\w.]){re.escape(name)}\.", text) is not None


# NodeVisitor dispatches on ``visit_<NodeClass>`` names, so pylint's snake_case rule does not apply.
# pylint: disable=invalid-name
class _UsageCollector(ast.NodeVisitor):
    """Walk a module recording, for fixed names, the attribute chains read through them.

    Args:
        names: Names to track.
    """

    def __init__(self, names: Collection[str]):
        self.usages = {name: NameUsage() for name in names}

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Record a whole attribute chain rooted at a tracked name; recurse otherwise.

        Args:
            node: Outermost attribute of a chain such as ``p.a.b``.
        """
        chain: list[str] = []
        base: ast.expr = node
        while isinstance(base, ast.Attribute):
            chain.append(base.attr)
            base = base.value
        if isinstance(base, ast.Name) and base.id in self.usages:
            usage = self.usages[base.id]
            if isinstance(node.ctx, ast.Load):
                usage.chains.add(".".join(reversed(chain)))
            else:
                usage.escapes = True
        else:
            self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        """Follow a string that references a tracked name, such as a quoted annotation.

        Args:
            node: A constant; only strings are inspected.
        """
        if not isinstance(node.value, str):
            return
        mentioned = [name for name in self.usages if _mentions(node.value, name)]
        if not mentioned:
            return
        try:
            expression = ast.parse(node.value, mode="eval")
        except (SyntaxError, ValueError):
            for name in mentioned:
                self.usages[name].escapes = True
            return
        self.visit(expression)

    def visit_Name(self, node: ast.Name) -> None:
        """Mark a tracked name that is used by itself.

        Names that start an attribute chain never get here: ``visit_Attribute`` consumes them.

        Args:
            node: A name load, store or delete.
        """
        if node.id in self.usages:
            self.usages[node.id].escapes = True


# pylint: enable=invalid-name


def collect_name_usage(tree: ast.Module, names: Collection[str]) -> dict[str, NameUsage]:
    """Find how a module uses some imported names.

    Shadowing by function parameters or local variables, and class or function
    definitions that reuse a name, are not detected.

    Args:
        tree: Parsed module.
        names: Names bound by imports whose use is of interest.

    Returns:
        The usage of each name, including those never used.
    """
    collector = _UsageCollector(names)
    collector.visit(tree)
    return collector.usages


class UseContext(StrEnum):
    """Where a module reads a name, which decides how cheaply an import can be moved.

    Attributes:
        ANNOTATION: In a type annotation only.
        FUNCTION: Inside a function or lambda body, run only when it is called.
        MODULE: At module or class level, run when the module is imported.
    """

    ANNOTATION = "annotation"
    FUNCTION = "function"
    MODULE = "module"


def _names_in_text(text: str, names: Collection[str]) -> list[str]:
    """Return the tracked names a string mentions as whole identifiers.

    Args:
        text: String constant, typically a quoted annotation.
        names: Tracked names.

    Returns:
        The names that appear in the string.
    """
    return [name for name in names if re.search(rf"(?<![\w.]){re.escape(name)}\b", text)]


# NodeVisitor dispatches on ``visit_<NodeClass>`` names, so pylint's snake_case rule does not apply.
# pylint: disable=invalid-name
class _ContextCollector(ast.NodeVisitor):
    """Walk a module recording in which contexts fixed names are read.

    Args:
        names: Names to track.
    """

    def __init__(self, names: Collection[str]):
        self.found: dict[str, set[UseContext]] = {name: set() for name in names}
        self.context = UseContext.MODULE

    def _visit_in(self, node: ast.AST, context: UseContext) -> None:
        """Visit a node with a given context, then restore the previous one.

        Args:
            node: Node to visit.
            context: Context its names are read in.
        """
        previous, self.context = self.context, context
        self.visit(node)
        self.context = previous

    def _visit_arguments(self, arguments: ast.arguments) -> None:
        """Visit the defaults (evaluated where the function is defined) and the annotations.

        Args:
            arguments: Arguments of a function or lambda.
        """
        for default in [*arguments.defaults, *arguments.kw_defaults]:
            if default is not None:
                self.visit(default)
        every = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        every += [arg for arg in (arguments.vararg, arguments.kwarg) if arg is not None]
        for arg in every:
            if arg.annotation is not None:
                self._visit_in(arg.annotation, UseContext.ANNOTATION)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Visit decorators and defaults in place, annotations as such, the body as function code.

        Args:
            node: A function or method definition.
        """
        for decorator in node.decorator_list:
            self.visit(decorator)
        for type_param in node.type_params:
            self.visit(type_param)
        self._visit_arguments(node.args)
        if node.returns is not None:
            self._visit_in(node.returns, UseContext.ANNOTATION)
        for statement in node.body:
            self._visit_in(statement, UseContext.FUNCTION)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        """Visit a lambda's defaults in place and its body as function code.

        Args:
            node: A lambda expression.
        """
        self._visit_arguments(node.args)
        self._visit_in(node.body, UseContext.FUNCTION)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Visit an annotated assignment's annotation as such, the rest in place.

        Args:
            node: An annotated assignment.
        """
        self._visit_in(node.annotation, UseContext.ANNOTATION)
        self.visit(node.target)
        if node.value is not None:
            self.visit(node.value)

    def visit_Name(self, node: ast.Name) -> None:
        """Record the current context for a tracked name.

        Args:
            node: A name.
        """
        if node.id in self.found:
            self.found[node.id].add(self.context)

    def visit_Constant(self, node: ast.Constant) -> None:
        """Count names mentioned in a quoted annotation as annotation uses.

        Args:
            node: A constant; only strings inside annotations are inspected.
        """
        if self.context is UseContext.ANNOTATION and isinstance(node.value, str):
            for name in _names_in_text(node.value, self.found):
                self.found[name].add(UseContext.ANNOTATION)


# pylint: enable=invalid-name


def collect_use_contexts(
    tree: ast.Module, names: Collection[str]
) -> dict[str, frozenset[UseContext]]:
    """Find in which contexts a module reads some names.

    Shadowing by parameters or local variables is not detected.

    Args:
        tree: Parsed module.
        names: Names of interest, typically the ones its imports bind.

    Returns:
        The contexts of each name; empty for names never read.
    """
    collector = _ContextCollector(names)
    collector.visit(tree)
    return {name: frozenset(found) for name, found in collector.found.items()}


def bound_names_by_line(tree: ast.Module) -> dict[int, tuple[str, ...]]:
    """Map each import statement's line to the names it binds.

    Args:
        tree: Parsed module.

    Returns:
        The names per line; ``import a.b`` binds ``a`` and ``from x import *`` binds nothing.
    """
    found: dict[int, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.asname or alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [alias.asname or alias.name for alias in node.names if alias.name != "*"]
        else:
            continue
        if names:
            found.setdefault(node.lineno, []).extend(names)
    return {line: tuple(names) for line, names in found.items()}


@dataclass(frozen=True, slots=True)
class ImportEvidence:
    """What supports a refactoring step for one dependency between two modules.

    Attributes:
        file_path: Source file of the importing module, or None when unknown.
        lines: Lines of the import statements behind the dependency, sorted.
        symbols: Symbols those statements import by name, sorted.
        contexts: Where the importing module reads the names those statements bind. Empty
            means unknown (file unreadable, names never read, or a star import), never safe.
        postponed_annotations: Whether the importing module has
            ``from __future__ import annotations``, so its signature and module-level
            annotations are not evaluated at import time.
    """

    file_path: Path | None
    lines: tuple[int, ...]
    symbols: tuple[str, ...]
    contexts: frozenset[UseContext]
    postponed_annotations: bool = False


NO_EVIDENCE = ImportEvidence(None, (), (), frozenset())


POSTPONED_ANNOTATIONS_FEATURE = "annotations"


def postpones_annotations(tree: ast.Module) -> bool:
    """Tell whether a module has ``from __future__ import annotations``.

    Future imports must open the module, so only its top-level statements are checked.

    Args:
        tree: Parsed module.

    Returns:
        True when the module postpones the evaluation of its annotations.
    """
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == POSTPONED_ANNOTATIONS_FEATURE for alias in node.names)
        for node in tree.body
    )


def _parse_source(file_path: Path, encoding: str | None) -> ast.Module | None:
    """Read and parse a source file again, or give up quietly.

    Args:
        file_path: Python source file.
        encoding: Fallback encoding when the file declares none.

    Returns:
        The parsed module, or None when the file cannot be read or parsed any more.
    """
    try:
        source = file_path.read_text(encoding=detect_encoding(file_path, encoding))
        with warnings.catch_warnings():
            # The scan already reported these; repeating them on this on-demand path is noise.
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(source, filename=str(file_path))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError, RecursionError, LookupError):
        return None


def collect_import_evidence(
    module: ModuleInfo,
    pairs: Collection[tuple[str, str]],
    *,
    kinds: Collection[ImportKind],
    encoding: str | None,
) -> dict[tuple[str, str], ImportEvidence]:
    """Gather the evidence behind some dependencies of one module.

    The file is parsed again, so callers only ask for the modules they need.

    Args:
        module: Resolved module whose imports are inspected.
        pairs: ``(source, target)`` dependencies of interest; others are ignored.
        kinds: Import kinds that count (import-time only, or every kind).
        encoding: Fallback encoding when the file declares none.

    Returns:
        The evidence per requested dependency that this module has.
    """
    wanted = set(pairs)
    lines: dict[tuple[str, str], set[int]] = {}
    symbols: dict[tuple[str, str], set[str]] = {}
    for edge in module.imports:
        pair = (edge.source, edge.target)
        if edge.is_external or pair not in wanted or edge.kind not in kinds:
            continue
        lines.setdefault(pair, set())
        symbols.setdefault(pair, set())
        if edge.line_number is not None:
            lines[pair].add(edge.line_number)
        if edge.symbol_name is not None:
            symbols[pair].add(edge.symbol_name)
    if not lines:
        return {}
    tree = _parse_source(module.file_path, encoding)
    bound = bound_names_by_line(tree) if tree is not None else {}
    names = {name for found in lines.values() for line in found for name in bound.get(line, ())}
    contexts = collect_use_contexts(tree, names) if tree is not None else {}
    postponed = tree is not None and postpones_annotations(tree)
    evidence = {}
    for pair, found in lines.items():
        used = {name for line in found for name in bound.get(line, ())}
        pair_contexts = frozenset().union(*(contexts.get(name, frozenset()) for name in used))
        evidence[pair] = ImportEvidence(
            module.file_path,
            tuple(sorted(found)),
            tuple(sorted(symbols[pair])),
            pair_contexts,
            postponed_annotations=postponed,
        )
    return evidence
