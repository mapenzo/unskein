import json
import logging
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from unskein.ai.proxy import MODEL_INFO_PATH, is_proxy_model, proxy_supports_reasoning
from unskein.config import AIConfig

KEY = "sk-virtual-123"
# serve_forever checks for shutdown at this interval; the 0.5 s default slows every test.
SERVER_POLL_SECONDS = 0.01
MODEL_INFO = {
    "data": [
        {"model_name": "GPT Luna", "model_info": {"supports_reasoning": True}},
        {"model_name": "Plain Chat", "model_info": {"supports_reasoning": False}},
        {"model_name": "Unknown Kind", "model_info": {}},
    ]
}


@dataclass
class FakeProxy:
    """A local HTTP server that answers like the model info route of a LiteLLM Proxy.

    Attributes:
        status: HTTP status to answer with.
        body: Raw body to answer with.
        requests: Path and Authorization header of every request received.
        base: Base URL of the server, set once it is listening.
    """

    status: int = 200
    body: bytes = json.dumps(MODEL_INFO).encode()
    requests: list[tuple[str, str | None]] = field(default_factory=list)
    base: str = ""


@pytest.fixture
def fake_proxy() -> Iterator[FakeProxy]:
    """Serve a ``FakeProxy`` on a free local port for the duration of a test.

    Yields:
        The scriptable proxy, with ``base`` pointing at the server.
    """
    proxy = FakeProxy()

    class Handler(BaseHTTPRequestHandler):
        """Answer every GET with the proxy's scripted status and body."""

        def do_GET(self) -> None:  # noqa: N802 - name required by BaseHTTPRequestHandler
            """Record the request and send the scripted answer."""
            proxy.requests.append((self.path, self.headers.get("Authorization")))
            self.send_response(proxy.status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(proxy.body)

        def log_message(self, *args: Any) -> None:
            """Keep the test output quiet."""

    server = HTTPServer(("127.0.0.1", 0), Handler)
    proxy.base = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": SERVER_POLL_SECONDS}, daemon=True
    )
    thread.start()
    yield proxy
    server.shutdown()
    server.server_close()


def config_for(alias: str, base: str | None, api_key: str | None = KEY) -> AIConfig:
    """Build the AI settings of a model served through a LiteLLM Proxy.

    Args:
        alias: Model alias on the proxy.
        base: Proxy URL.
        api_key: Virtual key.

    Returns:
        The settings.
    """
    return AIConfig(model=f"litellm_proxy/{alias}", api_key=api_key, api_base=base)


def test_only_litellm_proxy_models_are_proxy_models() -> None:
    assert is_proxy_model("litellm_proxy/GPT Luna")
    assert not is_proxy_model("openai/gpt-4o-mini")


def test_the_proxy_says_an_alias_is_a_reasoning_model(fake_proxy: FakeProxy) -> None:
    assert proxy_supports_reasoning(config_for("GPT Luna", fake_proxy.base)) is True


def test_the_proxy_says_an_alias_is_not_a_reasoning_model(fake_proxy: FakeProxy) -> None:
    assert proxy_supports_reasoning(config_for("Plain Chat", fake_proxy.base)) is False


@pytest.mark.parametrize("alias", ["Unknown Kind", "Not Served"])
def test_an_alias_the_proxy_says_nothing_about_gives_no_answer(
    fake_proxy: FakeProxy, alias: str
) -> None:
    assert proxy_supports_reasoning(config_for(alias, fake_proxy.base)) is None


def test_the_query_sends_the_virtual_key_to_the_model_info_route(fake_proxy: FakeProxy) -> None:
    proxy_supports_reasoning(config_for("GPT Luna", f"{fake_proxy.base}/"))

    assert fake_proxy.requests == [(MODEL_INFO_PATH, f"Bearer {KEY}")]


def test_the_query_works_without_a_key(fake_proxy: FakeProxy) -> None:
    assert proxy_supports_reasoning(config_for("GPT Luna", fake_proxy.base, api_key=None))
    assert fake_proxy.requests == [(MODEL_INFO_PATH, None)]


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (401, b'{"error": "no access"}'),
        (200, b"<html>not json</html>"),
        (200, b'{"data": "not a list"}'),
        (200, b'["not", "an", "object"]'),
        (200, b'{"data": ["not an object"]}'),
    ],
)
def test_an_unusable_answer_gives_no_answer(
    fake_proxy: FakeProxy, status: int, body: bytes
) -> None:
    fake_proxy.status = status
    fake_proxy.body = body

    assert proxy_supports_reasoning(config_for("GPT Luna", fake_proxy.base)) is None


def test_an_unreachable_proxy_gives_no_answer() -> None:
    config = config_for("GPT Luna", f"http://127.0.0.1:{closed_port()}")

    assert proxy_supports_reasoning(config) is None


@pytest.mark.parametrize("base", [None, "ftp://proxy.example.com", "file:///etc/passwd"])
def test_no_query_without_an_http_api_base(base: str | None) -> None:
    assert proxy_supports_reasoning(config_for("GPT Luna", base)) is None


def test_a_failed_query_is_logged_without_the_key(
    fake_proxy: FakeProxy, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(logging.getLogger("unskein"), "propagate", True)
    caplog.set_level(logging.DEBUG, logger="unskein")
    fake_proxy.status = 401
    fake_proxy.body = json.dumps({"error": f"bad key {KEY}"}).encode()

    proxy_supports_reasoning(config_for("GPT Luna", fake_proxy.base))

    assert "GPT Luna" in caplog.text
    assert KEY not in caplog.text


def closed_port() -> int:
    """Return a local port that nothing listens on, so connecting to it is refused.

    Returns:
        The port number.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
