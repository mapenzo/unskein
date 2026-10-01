"""Ask a LiteLLM Proxy what it knows about one of its model aliases."""

import json
import logging
from http.client import HTTPException
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from unskein.config import AIConfig

logger = logging.getLogger("unskein")

PROXY_MODEL_PREFIX = "litellm_proxy/"
MODEL_INFO_PATH = "/model/info"
MODEL_INFO_TIMEOUT_SECONDS = 10
# A model list is a few kilobytes; anything far larger is not a proxy's answer.
MAX_MODEL_INFO_BYTES = 1_000_000
HTTP_SCHEMES = frozenset({"http", "https"})


def is_proxy_model(model: str) -> bool:
    """Tell whether a model is called through a LiteLLM Proxy.

    Args:
        model: LiteLLM model string.

    Returns:
        True for ``litellm_proxy/`` models.
    """
    return model.startswith(PROXY_MODEL_PREFIX)


def proxy_supports_reasoning(config: AIConfig) -> bool | None:
    """Ask the proxy whether the alias behind a ``litellm_proxy/`` model is a reasoning model.

    A proxy alias is a name its admin chose, so LiteLLM cannot tell from it what
    the real model is; the proxy can. Any failure just means "no answer": the
    caller falls back to what LiteLLM knows.

    Args:
        config: Model, virtual key and proxy URL.

    Returns:
        The proxy's ``supports_reasoning`` for the alias, or None when there is
        no http(s) URL, the query fails or the proxy says nothing about it.
    """
    if not config.api_base:
        return None
    alias = config.model.removeprefix(PROXY_MODEL_PREFIX)
    try:
        if urlsplit(config.api_base).scheme not in HTTP_SCHEMES:
            return None
        payload = _fetch_model_info(config.api_base, config.api_key)
    # An odd URL or reply must never stop the scan: the AI step only falls back.
    except (OSError, ValueError, HTTPException, RecursionError) as error:
        # Only the error type is logged: a provider message may repeat the key.
        logger.debug("Could not ask the LiteLLM Proxy about %s (%s)", alias, type(error).__name__)
        return None
    return _reasoning_flag(payload, alias)


def _fetch_model_info(api_base: str, api_key: str | None) -> Any:
    """Download the proxy's model list from its model info route.

    Args:
        api_base: Proxy URL, with or without a trailing slash.
        api_key: Virtual key; sent as a bearer token when present.

    Returns:
        The decoded JSON answer.

    Raises:
        OSError: If the proxy cannot be reached, times out or answers with an
            HTTP error (``URLError`` and ``HTTPError`` are ``OSError``).
        ValueError: If the URL is malformed or the answer is not JSON (an
            answer cut at ``MAX_MODEL_INFO_BYTES`` is not JSON either).
        HTTPException: If the reply is not valid HTTP or ends too early.
        RecursionError: If the JSON is nested too deeply to decode.
    """
    request = Request(f"{api_base.rstrip('/')}{MODEL_INFO_PATH}")
    if api_key:
        # Unredirected: a redirect, even to another host, never carries the key.
        request.add_unredirected_header("Authorization", f"Bearer {api_key}")
    with urlopen(request, timeout=MODEL_INFO_TIMEOUT_SECONDS) as response:
        return json.loads(response.read(MAX_MODEL_INFO_BYTES))


def _reasoning_flag(payload: Any, alias: str) -> bool | None:
    """Find what the model info answer says about one alias.

    Args:
        payload: Decoded model info answer; any shape is tolerated.
        alias: Model alias on the proxy.

    Returns:
        The alias's ``supports_reasoning``, or None if the answer does not say.
    """
    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("model_name") != alias:
            continue
        info = entry.get("model_info")
        flag = info.get("supports_reasoning") if isinstance(info, dict) else None
        if isinstance(flag, bool):
            return flag
    return None
