import pytest

from unskein.graph.proof import (
    CutProof,
    ProofReason,
    ProofResult,
    ProofVerdict,
)


def proof(verdict: ProofVerdict, reason: ProofReason | None = None) -> CutProof:
    return CutProof("a", "b", verdict, reason)


def test_count_groups_cuts_by_verdict() -> None:
    result = ProofResult(
        cuts=(
            proof(ProofVerdict.PROVEN),
            proof(ProofVerdict.PROVEN),
            proof(ProofVerdict.NOT_PROVEN, ProofReason.NEEDS_DESIGN),
            proof(ProofVerdict.BROKEN, ProofReason.EDGE_REMAINS),
        ),
        tangles_after=0,
        cycles_after=0,
        cycles_after_truncated=False,
    )
    assert result.count(ProofVerdict.PROVEN) == 2
    assert result.count(ProofVerdict.NOT_PROVEN) == 1
    assert result.count(ProofVerdict.BROKEN) == 1


def test_reason_values_are_their_lowercase_names() -> None:
    assert all(reason.value == reason.name.lower() for reason in ProofReason)


def test_cut_proof_is_frozen() -> None:
    with pytest.raises(AttributeError):
        proof(ProofVerdict.PROVEN).verdict = ProofVerdict.BROKEN  # type: ignore[misc]


def test_no_reason_is_left_without_a_producer_for_the_whole_module_bypass() -> None:
    assert "whole_module_import" not in {reason.value for reason in ProofReason}
