from unskein.ai.models import Problem
from unskein.report.markdown import filter_by_severity


def _problem(severity: str) -> Problem:
    return Problem(
        severity=severity,
        title=severity,
        description="",
        affected_modules=[],
        recommendation="",
    )


def test_filter_by_severity_keeps_threshold_and_above() -> None:
    problems = [_problem("low"), _problem("medium"), _problem("high")]
    kept = [p.severity for p in filter_by_severity(problems, "medium")]
    assert kept == ["medium", "high"]
