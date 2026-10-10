"""Name the design smell behind a cut that needs a design decision."""

import ast
from collections.abc import Collection
from dataclasses import dataclass

from unskein.graph.proof import ProofReason

DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
DETAIL_SEPARATOR = ", "


@dataclass(frozen=True, slots=True)
class Smell:
    """A design smell found behind a cut.

    Attributes:
        reason: Which smell.
        detail: Language-neutral evidence: the class names, or the setting names.
    """

    reason: ProofReason
    detail: str


def base_knows_subclass(
    source: ast.Module, target: ast.Module, symbols: Collection[str]
) -> Smell | None:
    """Find a base class that imports a class inheriting from it.

    Args:
        source: Syntax tree of the importing module.
        target: Syntax tree of the imported module.
        symbols: Names the importing module imports from the target.

    Returns:
        The smell when the target defines an imported class whose base is a class the
        source defines, else None.
    """
    defined = {node.name for node in source.body if isinstance(node, ast.ClassDef)}
    for node in target.body:
        if not isinstance(node, ast.ClassDef) or node.name not in symbols:
            continue
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in defined:
                return Smell(ProofReason.BASE_KNOWS_SUBCLASS, f"{base.id} <- {node.name}")
    return None


def _bound_by_import_or_definition(node: ast.stmt) -> set[str]:
    """Return the names a module-level import or definition binds.

    Args:
        node: A module-level statement.

    Returns:
        The names; empty for any other statement.
    """
    if isinstance(node, DEFINITIONS):
        return {node.name}
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {(a.asname or a.name).split(".")[0] for a in node.names if a.name != "*"}
    return set()


def config_snapshot(facade: ast.Module, read: Collection[str]) -> Smell | None:
    """Find settings that a package assigns plainly and a module copies at import time.

    Args:
        facade: Syntax tree of the package ``__init__``.
        read: Names the importing module reads while it is imported.

    Returns:
        The smell naming the settings, or None when none of the names is a plain
        assignment of the package.
    """
    assigned: set[str] = set()
    other: set[str] = set()
    for node in facade.body:
        if isinstance(node, ast.Assign):
            assigned.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(node.target, ast.Name):
            assigned.add(node.target.id)
        else:
            other |= _bound_by_import_or_definition(node)
    found = sorted(name for name in set(read) if name in assigned and name not in other)
    return Smell(ProofReason.CONFIG_SNAPSHOT, DETAIL_SEPARATOR.join(found)) if found else None
