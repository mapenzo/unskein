from pathlib import Path

import pytest

from unskein.graph.steps import STEP_COSTS, StepKind, choose_step
from unskein.parsers.usage import NO_EVIDENCE, ImportEvidence, UseContext

A, F, M = UseContext.ANNOTATION, UseContext.FUNCTION, UseContext.MODULE
FACADES = {"pkg", "pkg.sub"}


def evidence(
    contexts: set[UseContext], symbols: tuple[str, ...] = ("X",), *, postponed: bool = False
) -> ImportEvidence:
    """Build evidence for one dependency.

    Args:
        contexts: Where the imported names are read.
        symbols: Symbols imported by name.
        postponed: Whether the importing module has ``from __future__ import annotations``.

    Returns:
        The evidence.
    """
    return ImportEvidence(
        Path("a.py"), (1,), symbols, frozenset(contexts), postponed_annotations=postponed
    )


@pytest.mark.parametrize(
    ("source", "target", "found", "expected"),
    [
        ("pkg", "pkg.sub", evidence({M}), StepKind.PACKAGE_STRUCTURE),
        ("pkg", "pkg.sub.deep", evidence({A}), StepKind.PACKAGE_STRUCTURE),
        ("app.a", "app.b", evidence({A}), StepKind.TYPE_CHECKING),
        ("app.a", "pkg", evidence({A}), StepKind.TYPE_CHECKING),
        ("app.a", "pkg", evidence({M}), StepKind.BYPASS_FACADE),
        ("pkg.sub.x", "pkg", evidence({M}), StepKind.BYPASS_FACADE),
        ("app.a", "app.b", evidence({F}), StepKind.LAZY),
        ("app.a", "app.b", evidence({A, F}, postponed=True), StepKind.LAZY),
        ("app.a", "app.b", evidence({A, F}), StepKind.MOVE_SYMBOL),
        ("app.a", "app.b", evidence({A, F}, ("X", "Y", "Z")), StepKind.EXTRACT_SHARED),
        ("app.a", "app.b", evidence({M}, ("X", "Y")), StepKind.MOVE_SYMBOL),
        ("app.a", "app.b", evidence({M}, ("X", "Y", "Z")), StepKind.EXTRACT_SHARED),
        ("app.a", "app.b", evidence({M}, ()), StepKind.EXTRACT_SHARED),
        ("app.a", "app.b", NO_EVIDENCE, StepKind.EXTRACT_SHARED),
    ],
    ids=[
        "package_child",
        "package_grandchild",
        "annotation_only",
        "annotation_only_wins_over_facade",
        "into_a_facade",
        "child_into_its_parent_facade",
        "function_only",
        "annotation_and_function_postponed",
        "annotation_read_at_import_is_not_lazy",
        "annotation_read_at_import_many_symbols",
        "two_symbols",
        "three_symbols",
        "whole_module",
        "no_evidence",
    ],
)
def test_choose_step_picks_the_cheapest_applicable(
    source: str, target: str, found: ImportEvidence, expected: StepKind
) -> None:
    assert choose_step(source, target, found, facades=FACADES) is expected


def test_costs_rank_the_steps() -> None:
    order = sorted(StepKind, key=lambda kind: STEP_COSTS[kind])
    assert order == [
        StepKind.TYPE_CHECKING,
        StepKind.BYPASS_FACADE,
        StepKind.LAZY,
        StepKind.MOVE_SYMBOL,
        StepKind.EXTRACT_SHARED,
        StepKind.PACKAGE_STRUCTURE,
    ]
    assert STEP_COSTS[StepKind.PACKAGE_STRUCTURE] >= 100 * STEP_COSTS[StepKind.EXTRACT_SHARED]
