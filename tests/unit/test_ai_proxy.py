import json
import logging
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from unskein.ai import proxy as proxy_module
from unskein.ai.proxy import MODEL_INFO_PATH, is_proxy_model, proxy_supports_reasoning
from unskein.config import AIConfig

KEY = "sk-virtual-123"
# serve_forever checks for shutdown at this interval; the 0.5 s default slows every test.
SERVER_POLL_SECONDS = 0.01
PROXY_ENV_VARS = (
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
)
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
        location: Where to redirect to; set it with a 30x status.
        raw: Bytes written instead of a well-formed HTTP answer.
        delay_seconds: How long to wait before answering.
        requests: Path and Authorization header of every request received.
        base: Base URL of the server, set once it is listening.
    """

    status: int = 200
    body: bytes = json.dumps(MODEL_INFO).encode()
    location: str | None = None
    raw: bytes | None = None
    delay_seconds: float = 0
    requests: list[tuple[str, str | None]] = field(default_factory=list)
    base: str = ""


@contextmanager
def serving(proxy: FakeProxy) -> Iterator[FakeProxy]:
    """Serve a ``FakeProxy`` on a free local port while the block runs.

    Args:
        proxy: The scripted answers.

    Yields:
        The same proxy, with ``base`` pointing at the server.
    """

    class Handler(BaseHTTPRequestHandler):
        """Answer every GET with the proxy's scripted reply."""

        def do_GET(self) -> None:  # noqa: N802 - name required by BaseHTTPRequestHandler
            """Record the request and send the scripted answer."""
            proxy.requests.append((self.path, self.headers.get("Authorization")))
            time.sleep(proxy.delay_seconds)
            if proxy.raw is not None:
                self.wfile.write(proxy.raw)
                return
            self.send_response(proxy.status)
            if proxy.location:
                self.send_header("Location", proxy.location)
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
    try:
        yield proxy
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def fake_proxy(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeProxy]:
    """Serve a ``FakeProxy`` reached directly, never through an HTTP proxy of the machine.

    Args:
        monkeypatch: Pytest monkeypatch fixture.

    Yields:
        The scriptable proxy, with ``base`` pointing at the server.
    """
    for name in PROXY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    with serving(FakeProxy()) as proxy:
        yield proxy


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


def test_an_unreachable_proxy_gives_no_answer(fake_proxy: FakeProxy) -> None:
    config = config_for("GPT Luna", f"http://127.0.0.1:{closed_port()}")

    assert proxy_supports_reasoning(config) is None


@pytest.mark.parametrize("base", [None, "ftp://proxy.example.com", "file:///etc/passwd"])
def test_no_query_without_an_http_api_base(base: str | None) -> None:
    assert proxy_supports_reasoning(config_for("GPT Luna", base)) is None


@pytest.mark.parametrize("base", ["http://[::1", "http://host:abc", "https://exa mple.com"])
def test_a_malformed_api_base_gives_no_answer(base: str) -> None:
    assert proxy_supports_reasoning(config_for("GPT Luna", base)) is None


@pytest.mark.parametrize(
    "raw",
    [
        b"garbage\r\n\r\n",
        b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{"data"',
    ],
)
def test_a_garbled_or_truncated_reply_gives_no_answer(fake_proxy: FakeProxy, raw: bytes) -> None:
    fake_proxy.raw = raw

    assert proxy_supports_reasoning(config_for("GPT Luna", fake_proxy.base)) is None


def test_a_slow_proxy_gives_no_answer(
    fake_proxy: FakeProxy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(proxy_module, "MODEL_INFO_TIMEOUT_SECONDS", 0.05)
    fake_proxy.delay_seconds = 0.3

    assert proxy_supports_reasoning(config_for("GPT Luna", fake_proxy.base)) is None


def test_an_oversized_reply_is_cut_and_gives_no_answer(
    fake_proxy: FakeProxy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(proxy_module, "MAX_MODEL_INFO_BYTES", 10)

    assert proxy_supports_reasoning(config_for("GPT Luna", fake_proxy.base)) is None


def test_a_deeply_nested_reply_gives_no_answer(fake_proxy: FakeProxy) -> None:
    fake_proxy.body = b"[" * 100_000

    assert proxy_supports_reasoning(config_for("GPT Luna", fake_proxy.base)) is None


def test_a_redirect_never_carries_the_key_to_another_server(fake_proxy: FakeProxy) -> None:
    with serving(FakeProxy()) as elsewhere:
        fake_proxy.status = 302
        fake_proxy.location = f"{elsewhere.base}{MODEL_INFO_PATH}"

        proxy_supports_reasoning(config_for("GPT Luna", fake_proxy.base))

    assert all(authorization is None for _, authorization in elsewhere.requests)


def test_a_failed_query_is_logged_without_the_key(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(api_base: str, api_key: str | None) -> None:
        raise OSError(f"proxy said: bad key {api_key}")

    monkeypatch.setattr(proxy_module, "_fetch_model_info", fail)
    monkeypatch.setattr(logging.getLogger("unskein"), "propagate", True)
    caplog.set_level(logging.DEBUG, logger="unskein")

    proxy_supports_reasoning(config_for("GPT Luna", "https://litellm.example.com"))

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
