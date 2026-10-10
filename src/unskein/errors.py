"""Process exit codes and the expected-error exception type of the CLI."""

from enum import IntEnum, StrEnum


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


class ErrorKey(StrEnum):
    """Message keys of expected errors; each one has an ES/EN entry in ``i18n``.

    Attributes:
        PATH_NOT_FOUND: The path to scan does not exist or is not a directory.
        NO_FILES_FOUND: No Python files left after discovery and excludes.
        INVALID_TOML: A config file is not valid TOML.
        UNKNOWN_KEY: A config file has a table or key unskein does not know.
        INVALID_VALUE: A config value has the wrong type or is not allowed.
        CONFIG_EXISTS: ``unskein init`` or ``config save`` would overwrite an
            existing config file.
        CONFIG_NOT_FOUND: The config file to save does not exist.
        RUN_NEEDS_PROVE: ``untangle --run`` was given without ``--prove``.
        PYTHON_NOT_FOUND: The interpreter given to ``untangle --python`` does not exist.
    """

    PATH_NOT_FOUND = "path_not_found"
    NO_FILES_FOUND = "no_files_found"
    INVALID_TOML = "invalid_toml"
    UNKNOWN_KEY = "unknown_key"
    INVALID_VALUE = "invalid_value"
    CONFIG_EXISTS = "config_exists"
    CONFIG_NOT_FOUND = "config_not_found"
    RUN_NEEDS_PROVE = "run_needs_prove"
    PYTHON_NOT_FOUND = "python_not_found"


class UnskeinError(Exception):
    """Expected usage error: shown as a translated message, no traceback, exit code 1.

    Kept structured (key + params) so the CLI translates it; only the key
    reaches ``str()``/``repr()`` and params never carry an offending value,
    so a misplaced secret cannot leak into output or logs.

    Args:
        key: Message key of the error.
        params: Language-neutral message data, such as ``path`` or ``field``.
    """

    def __init__(self, key: ErrorKey, params: dict[str, str] | None = None):
        super().__init__(key)
        self.key = key
        self.params = params or {}


class ConfigError(UnskeinError):
    """Invalid configuration: ``INVALID_TOML``, ``UNKNOWN_KEY`` or ``INVALID_VALUE``."""
