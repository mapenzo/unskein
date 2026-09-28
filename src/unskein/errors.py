"""Process exit codes and the expected-error exception type of the CLI."""

from enum import IntEnum


class ExitCode(IntEnum):
    """Exit codes returned by ``unskein scan``.

    Attributes:
        OK: Analysis finished with no problems at or above ``--min-severity``.
        USAGE_ERROR: Invalid path, no Python files, or invalid configuration.
        HIGH_SEVERITY_FOUND: Analysis finished and found high-severity problems.
        INTERNAL_ERROR: Unexpected bug; the full traceback is shown.
    """

    OK = 0
    USAGE_ERROR = 1
    HIGH_SEVERITY_FOUND = 2
    INTERNAL_ERROR = 3


class UnskeinError(Exception):
    """Expected usage error: shown as a clean message, no traceback, exit code 1."""


class ConfigError(UnskeinError):
    """Invalid configuration, kept structured so the CLI can translate it.

    Only the message key reaches ``str()``/``repr()``; params never carry the
    offending value, so a misplaced secret cannot leak into output or logs.

    Args:
        key: Message key: ``invalid_toml``, ``unknown_key`` or ``invalid_value``.
        params: Language-neutral message data, such as ``file`` and ``field``.
    """

    def __init__(self, key: str, params: dict[str, str]):
        super().__init__(key)
        self.key = key
        self.params = params
