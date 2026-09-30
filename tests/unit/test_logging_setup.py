import io
import logging
import sys
from collections.abc import Iterator

import pytest
from rich.console import Console

from unskein.logging_setup import LOGGER_NAME, setup_logging


@pytest.fixture(autouse=True)
def restore_unskein_logger() -> Iterator[None]:
    """Remove the handlers a test installs on the ``unskein`` logger."""
    yield
    logging.getLogger(LOGGER_NAME).handlers.clear()


def test_console_logs_follow_a_redirected_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = setup_logging(verbose=False, log_file=None)
    redirected = io.StringIO()
    monkeypatch.setattr(sys, "stderr", redirected)
    logger.warning("after redirect")
    assert redirected.getvalue() == "after redirect\n"


def test_a_warning_during_the_spinner_is_printed_above_it_not_over_it() -> None:
    logger = setup_logging(verbose=False, log_file=None)
    screen = io.StringIO()
    console = Console(file=screen, force_terminal=True, width=60)
    with console.status("waiting for the model"):
        logger.warning("model call failed")
    assert "model call failed\n" in screen.getvalue()


def test_the_console_shows_only_warnings_unless_verbose(capsys: pytest.CaptureFixture[str]) -> None:
    logger = setup_logging(verbose=False, log_file=None)
    logger.info("hidden")
    logger.warning("shown")
    assert capsys.readouterr().err == "shown\n"
