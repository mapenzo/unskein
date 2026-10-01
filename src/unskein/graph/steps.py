"""Choose the refactoring step that removes one dependency, from static evidence."""

from collections.abc import Collection, Mapping
from enum import StrEnum
from types import MappingProxyType

from unskein.parsers.usage import ImportEvidence, UseContext

MAX_MOVABLE_SYMBOLS = 2


class StepKind(StrEnum):
    """How a dependency can be removed, cheapest first.

    Attributes:
        TYPE_CHECKING: The names are only read in annotations; import them under
            ``if TYPE_CHECKING:``.
        BYPASS_FACADE: The dependency goes to a package's ``__init__.py``; import from the
            module that defines the name instead.
        LAZY: The names are only read inside functions; import them there.
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


def _applicable_steps(
    source: str, target: str, evidence: ImportEvidence, facades: Collection[str]
) -> set[StepKind]:
    """List every step the evidence allows for one dependency.

    Args:
        source: Importing module.
        target: Imported module.
        evidence: What supports each step.
        facades: Names of the project's package facades (``__init__.py``).

    Returns:
        The applicable steps; ``EXTRACT_SHARED`` always applies.
    """
    if source in facades and target.startswith(f"{source}."):
        return {StepKind.PACKAGE_STRUCTURE}
    steps = {StepKind.EXTRACT_SHARED}
    contexts = evidence.contexts
    if contexts and contexts <= {UseContext.ANNOTATION}:
        steps.add(StepKind.TYPE_CHECKING)
    if contexts and contexts <= {UseContext.ANNOTATION, UseContext.FUNCTION}:
        steps.add(StepKind.LAZY)
    if target in facades:
        steps.add(StepKind.BYPASS_FACADE)
    if 1 <= len(evidence.symbols) <= MAX_MOVABLE_SYMBOLS:
        steps.add(StepKind.MOVE_SYMBOL)
    return steps


def choose_step(
    source: str, target: str, evidence: ImportEvidence, *, facades: Collection[str]
) -> StepKind:
    """Pick the cheapest step that removes a dependency.

    Args:
        source: Importing module.
        target: Imported module.
        evidence: What supports each step.
        facades: Names of the project's package facades (``__init__.py``).

    Returns:
        The step with the lowest cost in ``STEP_COSTS``.
    """
    return min(_applicable_steps(source, target, evidence, facades), key=STEP_COSTS.__getitem__)
