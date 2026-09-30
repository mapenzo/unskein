import os
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from unskein.ai.client import ENV_LOCAL_COST_MAP, load_litellm

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep every test independent of the developer's real config and environment.

    Points the user-wide config at a file that does not exist and removes all
    ``UNSKEIN_*`` environment variables.

    Args:
        tmp_path_factory: Pytest factory for temporary directories.
        monkeypatch: Pytest monkeypatch fixture.
    """
    missing = tmp_path_factory.mktemp("home") / "config.toml"
    monkeypatch.setattr("unskein.config.USER_CONFIG_PATH", missing)
    for name in list(os.environ):
        if name.startswith("UNSKEIN_"):
            monkeypatch.delenv(name)


@pytest.fixture
def make_project(tmp_path: Path) -> Callable[[dict[str, str]], Path]:
    """Write {relative_path: source} under tmp_path and return the project root."""

    def _make(files: dict[str, str]) -> Path:
        for rel, source in files.items():
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        return tmp_path

    return _make


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def simple_project() -> Path:
    return FIXTURES_DIR / "simple_project"


@pytest.fixture
def circular_imports() -> Path:
    return FIXTURES_DIR / "circular_imports"


@pytest.fixture
def reexport_chain() -> Path:
    return FIXTURES_DIR / "reexport_chain"


@pytest.fixture
def reexport_cycle() -> Path:
    return FIXTURES_DIR / "reexport_cycle"


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that reaches the network through ``litellm.completion``.

    Tests that need a model answer install ``fake_llm`` on top of this.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
    """
    monkeypatch.setenv(ENV_LOCAL_COST_MAP, "True")
    litellm = load_litellm()

    def refuse(**kwargs: object) -> None:
        raise AssertionError("test called a real LLM; use the fake_llm fixture")

    monkeypatch.setattr(litellm, "completion", refuse)


class FakeLLM:
    """Scriptable stand-in for ``litellm.completion`` that records every call.

    Attributes:
        content: Text the fake model answers with.
        finish_reason: Finish reason of the answer.
        error: Exception to raise instead of answering.
        response: A ready-made response object; overrides ``content``.
        calls: Keyword arguments of every call.
    """

    def __init__(self) -> None:
        self.content: str | None = "{}"
        self.finish_reason = "stop"
        self.error: Exception | None = None
        self.response: SimpleNamespace | None = None
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        """Record the call, then raise the scripted error or return the scripted answer."""
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
        litellm = load_litellm()
        message = {"role": "assistant", "content": self.content}
        return litellm.ModelResponse(
            model="fake",
            choices=[{"index": 0, "finish_reason": self.finish_reason, "message": message}],
            usage=litellm.Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    """Install a scriptable fake in place of ``litellm.completion``.

    Args:
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        The fake, to script answers and inspect calls.
    """
    fake = FakeLLM()
    monkeypatch.setattr(load_litellm(), "completion", fake)
    return fake
