"""Find which attributes a module reads through the names its imports bind."""

import ast
from collections.abc import Collection
from dataclasses import dataclass, field


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
