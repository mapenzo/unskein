import pytest

from unskein.ai.client import extract_json_block, parse_report, strip_reasoning_blocks
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
