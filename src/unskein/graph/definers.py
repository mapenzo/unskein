"""Find the module that defines a name a package facade re-exports, when that is stable."""

import ast
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field

from unskein.parsers.discovery import parse_source
from unskein.parsers.exports import name_binding
from unskein.parsers.indirection import (
    ReExportIndex,
    build_reexport_index,
    guarded_reexports,
    passes_guard,
    star_exports,
)
from unskein.parsers.models import ModuleInfo, ParseResult

DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
SET_ATTRIBUTE_CALLS = frozenset({"setattr", "delattr"})
NAME_ARGUMENT = 1
SEGMENT_SEPARATOR = "."
PACKAGE_INIT = "__init__.py"
MAX_HOPS = 16


@dataclass(slots=True)
class DefinerIndex:
    """What deciding the definer of a facade name needs, computed once per project.

    The trees and the set of reassigned names are filled on first use.

    Attributes:
        modules: Parsed modules by name.
        names: Every project module name, virtual ones included.
        index: Re-export index.
        guarded: Guarded re-exports.
        star_count: How many star imports of each (module, name) bring the name in.
        encoding: Fallback encoding when a file declares none.
        trees: Source of each module read again, by name; None when it cannot be read.
        reassigned: Attribute names something assigns, deletes or sets by string; None
            until it is computed.
    """

    modules: Mapping[str, ModuleInfo]
    names: frozenset[str]
    index: ReExportIndex
    guarded: frozenset[tuple[str, str]]
    star_count: Counter[tuple[str, str]]
    encoding: str | None
    trees: dict[str, ast.Module | None] = field(default_factory=dict)
    reassigned: frozenset[str] | None = None

    def _tree(self, module: str) -> ast.Module | None:
        """Read a project module again, once.

        Args:
            module: Dotted module name.

        Returns:
            Its syntax tree, or None when it is not a parsed module or cannot be read.
        """
        if module not in self.trees:
            info = self.modules.get(module)
            self.trees[module] = parse_source(info.file_path, self.encoding) if info else None
        return self.trees[module]

    def _reassigned_names(self) -> frozenset[str]:
        """Find every attribute name that something assigns, deletes or sets by string.

        Any ``obj.name = …`` counts, whatever ``obj`` is: the answer is conservative.

        Returns:
            The names, computed on the first call.
        """
        if self.reassigned is None:
            found: set[str] = set()
            for module in self.modules:
                tree = self._tree(module)
                if tree is None:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute) and isinstance(
                        node.ctx, (ast.Store, ast.Del)
                    ):
                        found.add(node.attr)
                    elif _sets_attribute_by_string(node):
                        found.add(node.args[NAME_ARGUMENT].value)  # type: ignore[attr-defined]
            self.reassigned = frozenset(found)
        return self.reassigned

    def _binds_once(self, module: str, name: str) -> bool:
        """Tell whether a module binds a re-exported name once, plainly and unconditionally.

        Args:
            module: A package or module the name passes through.
            name: The re-exported name.

        Returns:
            True for a single plain ``from x import name`` directly in the module body, or
            the only star import that brings the name.
        """
        tree = self._tree(module)
        if tree is None:
            return False
        binding = name_binding(tree, name)
        stars = self.star_count[(module, name)]
        if binding.uncertain or binding.sites + stars != 1:
            return False
        return stars == 1 or binding.plain_import

    def _defines_once(self, module: str, name: str) -> bool:
        """Tell whether a module defines a name once, as a top-level function or class.

        Args:
            module: The candidate definer.
            name: The name.

        Returns:
            True when exactly one top-level ``def`` or ``class`` binds it and nothing else.
        """
        tree = self._tree(module)
        if tree is None:
            return False
        binding = name_binding(tree, name)
        if binding.sites != 1 or binding.in_block or binding.uncertain:
            return False
        return any(isinstance(node, DEFINITIONS) and node.name == name for node in tree.body)

    def _imported_from(self, module: str, name: str) -> str | None:
        """Find the project module a module imports a name from, without renaming it.

        Re-exports are only indexed for packages, so a plain module that forwards a name
        (``from .deep import Thing``) is followed here.

        Args:
            module: A module that may only forward the name.
            name: The name.

        Returns:
            The dotted source module, or None when no top-level ``from x import name`` binds
            it or the source is not a project module.
        """
        tree = self._tree(module)
        info = self.modules.get(module)
        if tree is None or info is None:
            return None
        package = module if info.file_path.name == PACKAGE_INIT else module.rpartition(".")[0]
        for node in tree.body:
            if not (
                isinstance(node, ast.ImportFrom)
                and any(alias.name == name and alias.asname is None for alias in node.names)
            ):
                continue
            parts = package.split(SEGMENT_SEPARATOR) if package else []
            base = parts[: len(parts) - (node.level - 1)] if node.level else []
            source = SEGMENT_SEPARATOR.join([*base, *([node.module] if node.module else [])])
            return source if source in self.names else None
        return None

    def definer(self, facade: str, name: str) -> str | None:
        """Find the module that defines a name the facade offers.

        Args:
            facade: A package whose ``__init__`` offers the name.
            name: The name.

        Returns:
            The dotted defining module, or None when the name is reassigned somewhere, is a
            submodule of the facade, passes a guard, is defined by the facade itself, or
            some module on the way does not bind it exactly once, plainly.
        """
        if name in self._reassigned_names():
            return None
        if f"{facade}{SEGMENT_SEPARATOR}{name}" in self.names:
            return None
        if passes_guard(facade, name, self.index, self.guarded):
            return None
        hops: list[str] = []
        module = facade
        while len(hops) < MAX_HOPS:
            if (module, name) in self.index:
                forwarded = self.index[(module, name)]
            elif self._defines_once(module, name):
                break
            else:
                forwarded = self._imported_from(module, name)
            if forwarded is None or forwarded in hops or forwarded == facade:
                return None
            hops.append(module)
            module = forwarded
        else:
            return None
        if module == facade or not all(self._binds_once(hop, name) for hop in hops):
            return None
        origin = module
        return origin


def _sets_attribute_by_string(node: ast.AST) -> bool:
    """Tell whether a node is ``setattr(x, "name", …)`` or ``delattr(x, "name")``.

    Args:
        node: Any node.

    Returns:
        True for such a call with a literal string name.
    """
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in SET_ATTRIBUTE_CALLS
        and len(node.args) > NAME_ARGUMENT
        and isinstance(node.args[NAME_ARGUMENT], ast.Constant)
        and isinstance(node.args[NAME_ARGUMENT].value, str)
    )


def build_definer_index(result: ParseResult, encoding: str | None) -> DefinerIndex:
    """Build the index of a parsed project.

    Args:
        result: Parsed project, re-exports resolved.
        encoding: Fallback encoding when a file declares none.

    Returns:
        The index; nothing is read until a definer is asked for.
    """
    stars = star_exports(result.modules, result.re_exports)
    star_count: Counter[tuple[str, str]] = Counter()
    for (module, _), names in stars.items():
        star_count.update((module, name) for name in names)
    return DefinerIndex(
        modules={module.name: module for module in result.modules},
        names=frozenset(module.name for module in result.modules) | frozenset(result.virtual),
        index=build_reexport_index(result.re_exports, stars),
        guarded=guarded_reexports(result.re_exports, stars),
        star_count=star_count,
        encoding=encoding,
    )
