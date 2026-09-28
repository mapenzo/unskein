"""Configure the ``unskein`` logger: clean console output plus an optional log file."""

import logging
from pathlib import Path

LOGGER_NAME = "unskein"


def setup_logging(verbose: bool, log_file: Path | None) -> logging.Logger:
    """Configure the ``unskein`` logger for one CLI run.

    The console always shows plain messages (WARNING, or DEBUG when verbose).
    A timestamped file handler is added only when a log file is requested, so
    nothing is written to disk unless asked. API keys must never be logged.

    Args:
        verbose: Whether to show DEBUG messages on the console.
        log_file: File to also write DEBUG logs to, or None for console only.

    Returns:
        The configured logger, which does not propagate to the root logger.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    logger.handlers.clear()

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(file_handler)

    return logger
