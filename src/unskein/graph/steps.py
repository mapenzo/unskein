"""Choose the refactoring step that removes one dependency, from static evidence."""

from collections.abc import Collection, Mapping
from enum import StrEnum
from types import MappingProxyType

from unskein.parsers.usage import ImportEvidence, UseContext

MAX_MOVABLE_SYMBOLS = 2


class StepKind(StrEnum):
    """How a dependency can be removed, cheapest first.

    Attributes:
        TYPE_CHECKING: The names are only read in annotations that are not evaluated at
            import (postponed or quoted); import them under ``if TYPE_CHECKING:``.
        BYPASS_FACADE: The dependency goes to a package's ``__init__.py``; import from the
            module that defines the name instead (not offered when the facade defines every
            imported name itself). A whole-module import that is only read inside functions
            gets LAZY instead.
        LAZY: The names are only read inside functions (or in annotations too, when the
            module postpones them); import them there.
        MOVE_SYMBOL: One or two symbols are imported; move them out of the cycle.
        EXTRACT_SHARED: Much is shared; extract it to a new module both can import.
        PACKAGE_STRUCTURE: A package imports one of its own submodules; only reorganizing
            the package removes it.
    """

    TYPE_CHECKING = "type_checking"
    BYPASS_FACADE = "bypass_facade"
    LAZY = "lazy"
    MOVE_SYMBOL = "move_symbol"
    EXTRACT_SHARED = "extract_shared"
    PACKAGE_STRUCTURE = "package_structure"


# Steps that remove the dependency itself; lazy and type-only imports keep it in the design.
STRUCTURAL_STEPS = frozenset(
    {
        StepKind.BYPASS_FACADE,
        StepKind.MOVE_SYMBOL,
        StepKind.EXTRACT_SHARED,
        StepKind.PACKAGE_STRUCTURE,
    }
)

# Calibrated on networkx, rich, aiohttp and litellm (docs/architecture.md, `untangle`): a
# package importing its own submodule is so expensive that it is only cut when no other
# edge breaks the cycle.
STEP_COSTS: Mapping[StepKind, int] = MappingProxyType(
    {
        StepKind.TYPE_CHECKING: 1,
        StepKind.BYPASS_FACADE: 2,
        StepKind.LAZY: 3,
        StepKind.MOVE_SYMBOL: 4,
        StepKind.EXTRACT_SHARED: 6,
        StepKind.PACKAGE_STRUCTURE: 1000,
    }
)


DEFERRED_CONTEXTS = frozenset({UseContext.ANNOTATION, UseContext.QUOTED})


def _deferred_annotations(evidence: ImportEvidence) -> bool:
    """Tell whether every read of the names happens where Python never evaluates it.

    A signature annotation is evaluated when the function is defined, so moving its
    import under ``TYPE_CHECKING`` raises ``NameError`` on Python 3.12 and 3.13 (3.14
    evaluates annotations lazily). Only postponed or quoted annotations are safe.

    Args:
        evidence: Where the names are read and whether annotations are postponed.

    Returns:
        True when the names are read only in postponed or quoted annotations.
    """
    contexts = evidence.contexts
    if not contexts or not contexts <= DEFERRED_CONTEXTS:
        return False
    return evidence.postponed_annotations or contexts == {UseContext.QUOTED}


def _lazy_applies(evidence: ImportEvidence) -> bool:
    """Tell whether importing the names inside the functions that read them is safe.

    Signature and module-level annotations run at import time unless the module has
    ``from __future__ import annotations``; a name read there must exist then.

    Args:
        evidence: Where the names are read and whether annotations are postponed.

    Returns:
        True when every read happens after import time.
    """
    contexts = evidence.contexts
    if not contexts:
        return False
    if contexts <= {UseContext.FUNCTION, UseContext.QUOTED}:
        return True
    return evidence.postponed_annotations and contexts <= {
        UseContext.ANNOTATION,
        UseContext.QUOTED,
        UseContext.FUNCTION,
    }


def _bypass_applies(evidence: ImportEvidence, own_names: Collection[str]) -> bool:
    """Tell whether the imported names can come from somewhere other than the facade.

    A whole-module import (no symbols) is bypassed only when moving it into the functions
    that read it is not enough: replacing every ``pkg.X`` by a direct import cannot be
    proven when ``X`` is state that something reassigns, and the lazy step removes the same
    import-time dependency with one edit.

    Args:
        evidence: What the dependency imports by name.
        own_names: Names the facade defines itself (not re-exports nor submodules).

    Returns:
        False when names are imported and the facade defines every one of them, or when a
        whole-module import is only read after import time; True otherwise.
    """
    if not evidence.symbols:
        return not _lazy_applies(evidence)
    return not set(evidence.symbols) <= set(own_names)


def _applicable_steps(
    source: str,
    target: str,
    evidence: ImportEvidence,
    *,
    facades: Mapping[str, Collection[str]],
) -> set[StepKind]:
    """List every step the evidence allows for one dependency.

    Args:
        source: Importing module.
        target: Imported module.
        evidence: What supports each step.
        facades: The project's package facades (``__init__.py``), each with the names it
            defines itself.

    Returns:
        The applicable steps; ``EXTRACT_SHARED`` always applies.
    """
    if source in facades and target.startswith(f"{source}."):
        return {StepKind.PACKAGE_STRUCTURE}
    steps = {StepKind.EXTRACT_SHARED}
    if _deferred_annotations(evidence):
        steps.add(StepKind.TYPE_CHECKING)
    if _lazy_applies(evidence):
        steps.add(StepKind.LAZY)
    if target in facades and _bypass_applies(evidence, facades[target]):
        steps.add(StepKind.BYPASS_FACADE)
    if 1 <= len(evidence.symbols) <= MAX_MOVABLE_SYMBOLS:
        steps.add(StepKind.MOVE_SYMBOL)
    return steps


def choose_step(
    source: str,
    target: str,
    evidence: ImportEvidence,
    *,
    facades: Mapping[str, Collection[str]],
) -> StepKind:
    """Pick the cheapest step that removes a dependency.

    Args:
        source: Importing module.
        target: Imported module.
        evidence: What supports each step.
        facades: The project's package facades (``__init__.py``), each with the names it
            defines itself.

    Returns:
        The step with the lowest cost in ``STEP_COSTS``.
    """
    steps = _applicable_steps(source, target, evidence, facades=facades)
    return min(steps, key=STEP_COSTS.__getitem__)
