import pytest

from unskein.ai.models import AIFailure, AIOutcome, AIReport


def make_report() -> AIReport:
    """Build a minimal valid report.

    Returns:
        A report with no problems.
    """
    return AIReport(summary="ok", architecture_health="good", problems=[])


def test_outcome_with_a_report_is_valid() -> None:
    assert AIOutcome(report=make_report()).failure is None


def test_outcome_with_a_failure_is_valid() -> None:
    outcome = AIOutcome(failure=AIFailure.CALL_ERROR, error_type="AuthenticationError")
    assert outcome.report is None
    assert outcome.error_type == "AuthenticationError"


def test_outcome_needs_exactly_one_of_report_and_failure() -> None:
    with pytest.raises(ValueError):
        AIOutcome()
    with pytest.raises(ValueError):
        AIOutcome(report=make_report(), failure=AIFailure.TIMEOUT)


def test_failure_values_are_stable_keys() -> None:
    assert [failure.value for failure in AIFailure] == ["timeout", "call_error", "invalid_response"]


def test_code_snippet_is_hidden_from_the_schema_the_model_sees() -> None:
    problem_schema = AIReport.model_json_schema()["$defs"]["Problem"]["properties"]
    assert "code_snippet" not in problem_schema
    assert "severity" in problem_schema
