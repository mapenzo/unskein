import os

import pytest

from unskein.ai.client import (
    DEFAULT_TEMPERATURE,
    DIRECT_CALL_TIMEOUT_SECONDS,
    REASONING_TEMPERATURE,
    build_profile,
    extract_json_block,
    load_litellm,
    parse_report,
    strip_reasoning_blocks,
)
from unskein.ai.models import AIReport

GOOD_REPORT = AIReport(summary="ok", architecture_health="fair", problems=[]).model_dump_json()


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
