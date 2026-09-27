from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    USAGE_ERROR = 1
    HIGH_SEVERITY_FOUND = 2
    INTERNAL_ERROR = 3


class UnskeinError(Exception):
    """Expected usage error: shown as a clean message, no traceback, exit code 1."""
