"""Import modules in isolated subprocesses to learn which ones load."""

import re
import subprocess
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from unskein.graph.proof import ProbeResult

PROBE_CODE = (
    "import importlib, sys\nsys.path[:0] = sys.argv[2:]\nimportlib.import_module(sys.argv[1])\n"
)
PROBE_TIMEOUT_SECONDS = 60
MAX_ERROR_CHARS = 300
TIMEOUT_ERROR = "timeout"
TRACEBACK_FILE = re.compile(r'File "([^"]+)"')
INIT_FILE = "__init__.py"


@dataclass(frozen=True, slots=True)
class ProbeJob:
    """How to import modules in subprocesses.

    Attributes:
        python: Interpreter that runs each import.
        cwd: Working directory of the subprocesses.
        roots: Directories placed on ``sys.path`` ahead of everything else.
        timeout: Seconds one import may take before it is reported as a timeout.
        workers: How many subprocesses run at the same time.
    """

    python: Path
    cwd: Path
    roots: tuple[Path, ...]
    timeout: float
    workers: int


def _last_line(text: str) -> str:
    """Return the last non-empty line of a text, shortened.

    Args:
        text: The standard error of a subprocess.

    Returns:
        That line, at most ``MAX_ERROR_CHARS`` long.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    return (lines[-1] if lines else "").strip()[:MAX_ERROR_CHARS]


def _probe_one(job: ProbeJob, module: str) -> ProbeResult:
    """Import one module in a fresh isolated interpreter.

    ``-I`` keeps the working directory and the user site off ``sys.path``, and ``-B``
    keeps the run from writing bytecode next to the code it imports.

    Args:
        job: How to run the import.
        module: Dotted module name.

    Returns:
        Whether it imported and, when not, the last error line and the files in the
        traceback.
    """
    command = [str(job.python), "-I", "-B", "-c", PROBE_CODE, module, *map(str, job.roots)]
    try:
        done = subprocess.run(
            command,
            cwd=job.cwd,
            capture_output=True,
            text=True,
            timeout=job.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(module, False, TIMEOUT_ERROR)
    except OSError as error:
        return ProbeResult(module, False, str(error)[:MAX_ERROR_CHARS])
    if done.returncode == 0:
        return ProbeResult(module, True)
    return ProbeResult(
        module, False, _last_line(done.stderr), tuple(TRACEBACK_FILE.findall(done.stderr))
    )


def run_probes(job: ProbeJob, modules: Sequence[str]) -> dict[str, ProbeResult]:
    """Import every module in its own subprocess, several at a time.

    Threads are enough: each one only waits for its subprocess.

    Args:
        job: How to run the imports.
        modules: Dotted module names.

    Returns:
        The outcome per module.
    """
    with ThreadPoolExecutor(max_workers=max(1, job.workers)) as executor:
        results = executor.map(lambda module: _probe_one(job, module), modules)
        return {result.module: result for result in results}


def import_roots(modules: Mapping[str, Path], copy_root: Path) -> tuple[Path, ...]:
    """Find the directories that make the modules importable by their dotted names.

    Args:
        modules: Module name to its file path relative to the copy root.
        copy_root: Root of the copy.

    Returns:
        The distinct directories to put on ``sys.path``, sorted.
    """
    roots: set[Path] = set()
    for name, relative in modules.items():
        depth = len(name.split(".")) - 1 + (1 if relative.name == INIT_FILE else 0)
        if depth < len(relative.parents):
            roots.add(copy_root / relative.parents[depth])
    return tuple(sorted(roots))
