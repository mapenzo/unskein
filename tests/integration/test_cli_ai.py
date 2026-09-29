import re
from pathlib import Path
from typing import Any

from click.testing import Result
from typer.testing import CliRunner

from unskein.ai.client import load_litellm
from unskein.ai.models import AIReport, Problem
from unskein.cli import app
from unskein.errors import ExitCode

runner = CliRunner()
SECRET = "sk-SECRET-XYZ"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def flat(result: Result) -> str:
    """Return the CLI output as one line of plain text.

    Rich wraps long lines and CI forces ANSI colors; both would split the phrases
    the tests look for.

    Args:
        result: The CliRunner result.

    Returns:
        Output without ANSI codes and with whitespace collapsed.
    """
    return " ".join(ANSI_ESCAPE.sub("", result.output).split())


def scan_with_model(project: Path, *args: str) -> Result:
    """Run ``unskein scan`` with a model configured through the environment.

    Args:
        project: Project to scan.
        *args: Extra CLI arguments.

    Returns:
        The CliRunner result.
    """
    return runner.invoke(
        app,
        ["scan", str(project), "--lang", "en", *args],
        env={"UNSKEIN_AI_MODEL": "ollama/qwen2.5-coder:7b"},
    )


def report_json(*problems: Problem) -> str:
    """Serialize an AI report holding the given problems.

    Args:
        *problems: Problems of the report.

    Returns:
        The report as JSON text.
    """
    report = AIReport(
        summary="The imports form a knot.",
        architecture_health="concerning",
        problems=list(problems),
    )
    return report.model_dump_json()


def high_problem(modules: list[str]) -> Problem:
    """Build a high-severity problem.

    Args:
        modules: Affected modules.

    Returns:
        The problem.
    """
    return Problem(
        severity="high",
        title="Cycle between a and b",
        description="They import each other.",
        affected_modules=modules,
        recommendation="Extract the shared code.",
    )


def test_a_high_problem_shows_in_the_report_and_exits_2(
    circular_imports: Path, fake_llm: Any
) -> None:
    fake_llm.content = report_json(high_problem(["app.a", "app.b"]))
    result = scan_with_model(circular_imports)
    assert result.exit_code == ExitCode.HIGH_SEVERITY_FOUND
    assert "The imports form a knot." in flat(result)
    assert "Cycle between a and b" in flat(result)


def test_min_severity_filters_the_shown_problems(circular_imports: Path, fake_llm: Any) -> None:
    low = high_problem(["app.a"]).model_copy(update={"severity": "low", "title": "Minor thing"})
    fake_llm.content = report_json(low)
    result = scan_with_model(circular_imports, "--min-severity", "high")
    assert "Minor thing" not in flat(result)
    assert result.exit_code == ExitCode.OK


def test_an_unusable_answer_keeps_the_report_and_exits_0(
    circular_imports: Path, fake_llm: Any
) -> None:
    fake_llm.content = "I cannot help with that."
    result = scan_with_model(circular_imports)
    assert result.exit_code == ExitCode.OK
    assert "Analysis of circular_imports" in flat(result)
    assert "does not follow the expected format" in flat(result)


def test_hallucinated_modules_never_reach_the_report(circular_imports: Path, fake_llm: Any) -> None:
    fake_llm.content = report_json(high_problem(["ghost.module"]))
    result = scan_with_model(circular_imports)
    assert result.exit_code == ExitCode.OK
    assert "ghost.module" not in flat(result)
    assert "Cycle between a and b" not in flat(result)


def test_a_provider_error_is_named_but_its_message_and_the_key_are_not_shown(
    circular_imports: Path, fake_llm: Any
) -> None:
    fake_llm.error = load_litellm().AuthenticationError(
        f"Incorrect API key provided: {SECRET}", model="m", llm_provider="p"
    )
    result = scan_with_model(circular_imports, "--api-key", SECRET)
    assert result.exit_code == ExitCode.OK
    assert "AuthenticationError" in flat(result)
    assert "Incorrect API key" not in flat(result)
    assert SECRET not in flat(result)


def test_no_ai_makes_no_model_call_even_with_a_model_configured(
    circular_imports: Path, fake_llm: Any
) -> None:
    result = scan_with_model(circular_imports, "--no-ai")
    assert result.exit_code == ExitCode.OK
    assert fake_llm.calls == []
    assert "--no-ai" in flat(result)


def test_spanish_reports_get_spanish_ai_notices(circular_imports: Path, fake_llm: Any) -> None:
    fake_llm.content = "no json"
    result = runner.invoke(
        app,
        ["scan", str(circular_imports), "--lang", "es"],
        env={"UNSKEIN_AI_MODEL": "ollama/x"},
    )
    assert "no cumple el formato esperado" in flat(result)
