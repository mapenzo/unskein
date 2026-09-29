import json
import logging
import os
from types import SimpleNamespace
from typing import Any

import pytest

from unskein.ai.client import (
    DEFAULT_TEMPERATURE,
    DIRECT_CALL_TIMEOUT_SECONDS,
    REASONING_TEMPERATURE,
    AIClient,
    build_profile,
    extract_json_block,
    load_litellm,
    parse_report,
    strip_reasoning_blocks,
)
from unskein.ai.models import AIFailure, AIReport
from unskein.config import AIConfig

GOOD_REPORT = AIReport(summary="ok", architecture_health="fair", problems=[]).model_dump_json()
ECHOED_SCHEMA = json.dumps(AIReport.model_json_schema())


def test_extract_prefers_a_fenced_json_block() -> None:
    raw = 'Here you go:\n```json\n{"a": {"b": 1}}\n```\nHope it helps {not json}'
    assert extract_json_block(raw) == '{"a": {"b": 1}}'


def test_extract_falls_back_to_the_outermost_braces() -> None:
    assert extract_json_block('Sure! {"a": 1} Done.') == '{"a": 1}'


def test_extract_returns_none_without_json() -> None:
    assert extract_json_block("no json here") is None
    assert extract_json_block("} reversed {") is None


def test_strip_reasoning_blocks_removes_think_sections_with_braces() -> None:
    raw = '<think>maybe {"x": 1} first</think>\n{"a": 1}'
    assert strip_reasoning_blocks(raw).strip() == '{"a": 1}'


def test_parse_accepts_plain_json() -> None:
    assert parse_report(GOOD_REPORT) == AIReport.model_validate_json(GOOD_REPORT)


def test_parse_accepts_fenced_json_with_prose() -> None:
    assert parse_report(f"Result:\n```json\n{GOOD_REPORT}\n```") is not None


def test_parse_skips_an_echoed_schema_fence_before_the_answer() -> None:
    raw = f"```json\n{ECHOED_SCHEMA}\n```\n```json\n{GOOD_REPORT}\n```"
    assert parse_report(raw) == AIReport.model_validate_json(GOOD_REPORT)


def test_parse_skips_an_echoed_schema_fence_with_prose_between() -> None:
    raw = f"Schema:\n```json\n{ECHOED_SCHEMA}\n```\nMy answer:\n```json\n{GOOD_REPORT}\n```"
    assert parse_report(raw) == AIReport.model_validate_json(GOOD_REPORT)


def test_parse_returns_none_when_no_fenced_block_validates() -> None:
    assert parse_report(f"```json\n{ECHOED_SCHEMA}\n```\n```json\n{{}}\n```") is None


def test_parse_ignores_reasoning_before_the_answer() -> None:
    assert parse_report(f'<think>{{"draft": true}}</think>{GOOD_REPORT}') is not None


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "definitely not json",
        '{"summary": "ok"}',
        '{"summary": "s", "architecture_health": "great", "problems": []}',
        '{"summary": "s", "architecture_health": "fair", "problems": '
        '[{"severity": "HIGH", "title": "t", "description": "d", '
        '"affected_modules": [], "recommendation": "r"}]}',
    ],
)
def test_parse_returns_none_when_output_does_not_match_the_schema(raw: str) -> None:
    assert parse_report(raw) is None


def test_load_litellm_disables_remote_lookups(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LITELLM_LOCAL_MODEL_COST_MAP", raising=False)
    litellm = load_litellm()
    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"
    assert litellm.telemetry is False
    assert litellm.suppress_debug_info is True


@pytest.mark.parametrize(
    ("model", "temperature"),
    [
        ("gpt-5", REASONING_TEMPERATURE),
        ("o3-mini", REASONING_TEMPERATURE),
        ("litellm_proxy/gpt-5", REASONING_TEMPERATURE),
        ("gpt-4o", DEFAULT_TEMPERATURE),
        ("ollama/qwen2.5-coder:7b", DEFAULT_TEMPERATURE),
        ("litellm_proxy/my-opaque-alias", DEFAULT_TEMPERATURE),
    ],
)
def test_reasoning_models_get_temperature_one(model: str, temperature: float) -> None:
    assert build_profile(model).temperature == temperature


def test_response_format_follows_schema_support() -> None:
    assert build_profile("gpt-4o").response_format is AIReport
    assert build_profile("ollama/qwen2.5-coder:7b").response_format == {"type": "json_object"}


def test_only_direct_calls_get_a_timeout() -> None:
    assert build_profile("ollama/qwen2.5-coder:7b").timeout_seconds == DIRECT_CALL_TIMEOUT_SECONDS
    assert build_profile("litellm_proxy/gpt-4o").timeout_seconds is None


MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
SECRET = "sk-SECRET-123"
OLLAMA = "ollama/qwen2.5-coder:7b"


def make_client(model: str = OLLAMA, api_key: str | None = None) -> AIClient:
    """Build a client for a model.

    Args:
        model: LiteLLM model string.
        api_key: Optional API key.

    Returns:
        The client.
    """
    return AIClient(AIConfig(model=model, api_key=api_key, api_base="http://localhost:11434"))


def test_a_valid_answer_becomes_a_report(fake_llm: Any) -> None:
    fake_llm.content = GOOD_REPORT
    outcome = make_client().generate_report(MESSAGES)
    assert outcome.report is not None
    assert outcome.failure is None


def test_the_request_carries_the_profile(fake_llm: Any) -> None:
    fake_llm.content = GOOD_REPORT
    make_client(api_key=SECRET).generate_report(MESSAGES)
    request = fake_llm.calls[0]
    assert request["model"] == OLLAMA
    assert request["messages"] == MESSAGES
    assert request["temperature"] == DEFAULT_TEMPERATURE
    assert request["response_format"] == {"type": "json_object"}
    assert request["drop_params"] is True
    assert request["timeout"] == DIRECT_CALL_TIMEOUT_SECONDS
    assert request["api_key"] == SECRET
    assert request["api_base"] == "http://localhost:11434"


def test_proxy_calls_send_no_timeout(fake_llm: Any) -> None:
    fake_llm.content = GOOD_REPORT
    make_client("litellm_proxy/gpt-5").generate_report(MESSAGES)
    assert "timeout" not in fake_llm.calls[0]
    assert fake_llm.calls[0]["temperature"] == REASONING_TEMPERATURE


def test_profile_is_resolved_once_when_the_client_is_built(
    fake_llm: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    litellm = load_litellm()
    real_supports_reasoning = litellm.supports_reasoning
    lookups: list[str] = []

    def spy(model: str) -> bool:
        lookups.append(model)
        return real_supports_reasoning(model)

    monkeypatch.setattr(litellm, "supports_reasoning", spy)
    fake_llm.content = GOOD_REPORT
    client = make_client()
    client.generate_report(MESSAGES)
    client.generate_report(MESSAGES)
    assert lookups == [OLLAMA]


def test_timeout_is_reported_as_timeout(fake_llm: Any) -> None:
    fake_llm.error = load_litellm().Timeout("slow", model="m", llm_provider="p")
    outcome = make_client().generate_report(MESSAGES)
    assert outcome.failure is AIFailure.TIMEOUT


def test_provider_errors_are_call_errors_named_by_class(fake_llm: Any) -> None:
    fake_llm.error = load_litellm().AuthenticationError("bad", model="m", llm_provider="p")
    outcome = make_client().generate_report(MESSAGES)
    assert outcome.failure is AIFailure.CALL_ERROR
    assert outcome.error_type == "AuthenticationError"


def test_a_bug_is_not_swallowed(fake_llm: Any) -> None:
    fake_llm.error = RuntimeError("bug")
    with pytest.raises(RuntimeError):
        make_client().generate_report(MESSAGES)


@pytest.mark.parametrize("content", [None, "", "not json at all"])
def test_unusable_content_is_an_invalid_response(fake_llm: Any, content: str | None) -> None:
    fake_llm.content = content
    assert make_client().generate_report(MESSAGES).failure is AIFailure.INVALID_RESPONSE


def test_truncated_output_is_an_invalid_response(fake_llm: Any) -> None:
    fake_llm.content = GOOD_REPORT
    fake_llm.finish_reason = "length"
    assert make_client().generate_report(MESSAGES).failure is AIFailure.INVALID_RESPONSE


def test_a_response_without_choices_is_an_invalid_response(fake_llm: Any) -> None:
    fake_llm.response = SimpleNamespace(choices=[], usage=None)
    assert make_client().generate_report(MESSAGES).failure is AIFailure.INVALID_RESPONSE


@pytest.fixture(name="unskein_logs")
def make_unskein_logs(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Let ``caplog`` see the non-propagating ``unskein`` logger at DEBUG level.

    Args:
        caplog: Pytest log capture fixture.
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        The caplog fixture.
    """
    monkeypatch.setattr(logging.getLogger("unskein"), "propagate", True)
    caplog.set_level(logging.DEBUG, logger="unskein")
    return caplog


@pytest.mark.parametrize(
    "error_name", ["Timeout", "AuthenticationError", "RateLimitError", "BadRequestError"]
)
def test_the_api_key_never_reaches_logs_or_the_outcome(
    fake_llm: Any, unskein_logs: Any, error_name: str
) -> None:
    error_class = getattr(load_litellm(), error_name)
    fake_llm.error = error_class(f"provider says {SECRET}", model="m", llm_provider="p")
    client = make_client(api_key=SECRET)
    outcome = client.generate_report(MESSAGES)
    assert SECRET not in unskein_logs.text
    assert SECRET not in repr(outcome)
    assert SECRET not in repr(client.config)


def test_the_provider_message_is_logged_redacted_at_debug(fake_llm: Any, unskein_logs: Any) -> None:
    fake_llm.error = load_litellm().AuthenticationError(
        f"provider says {SECRET}", model="m", llm_provider="p"
    )
    make_client(api_key=SECRET).generate_report(MESSAGES)
    assert "provider says ***" in unskein_logs.text


def test_an_empty_api_key_does_not_mangle_the_logged_message(
    fake_llm: Any, unskein_logs: Any
) -> None:
    fake_llm.error = load_litellm().AuthenticationError(
        "provider says nothing", model="m", llm_provider="p"
    )
    make_client(api_key="").generate_report(MESSAGES)
    assert "provider says nothing" in unskein_logs.text


@pytest.mark.parametrize("content", [GOOD_REPORT, "not json"])
def test_the_api_key_never_reaches_logs_or_the_outcome_without_an_exception(
    fake_llm: Any, unskein_logs: Any, content: str
) -> None:
    fake_llm.content = content
    outcome = make_client(api_key=SECRET).generate_report(MESSAGES)
    assert SECRET not in unskein_logs.text
    assert SECRET not in repr(outcome)
