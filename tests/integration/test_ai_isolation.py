import os
import subprocess
import sys
from pathlib import Path

NO_NETWORK = """
import socket

def refuse(*args, **kwargs):
    raise SystemExit("network attempted")

socket.socket.connect = refuse
socket.getaddrinfo = refuse
from unskein.ai.client import load_litellm
load_litellm()
print("ok")
"""

SCAN_WITHOUT_AI = """
import sys
from typer.testing import CliRunner
from unskein.cli import app

CliRunner().invoke(app, ["scan", sys.argv[1], "--no-ai"])
print("litellm" in sys.modules)
"""


def run_python(script: str, *args: str, drop_env: str = "") -> subprocess.CompletedProcess[str]:
    """Run a Python snippet in a fresh interpreter.

    Args:
        script: Source code to run with ``-c``.
        *args: Arguments passed to the script.
        drop_env: Name of an environment variable to remove for the run.

    Returns:
        The completed process, with captured text output.
    """
    env = {name: value for name, value in os.environ.items() if name != drop_env}
    return subprocess.run(
        [sys.executable, "-c", script, *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_loading_litellm_opens_no_network_connection() -> None:
    completed = run_python(NO_NETWORK, drop_env="LITELLM_LOCAL_MODEL_COST_MAP")
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"


def test_importing_the_client_module_does_not_import_litellm() -> None:
    completed = run_python("import sys, unskein.ai.client; print('litellm' in sys.modules)")
    assert completed.stdout.strip() == "False"


def test_a_no_ai_scan_never_imports_litellm(circular_imports: Path) -> None:
    completed = run_python(SCAN_WITHOUT_AI, str(circular_imports))
    assert completed.stdout.strip().splitlines()[-1] == "False"
