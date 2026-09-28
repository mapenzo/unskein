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
