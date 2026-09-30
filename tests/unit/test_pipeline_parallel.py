from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

import pytest

from unskein import pipeline
from unskein.config import AnalysisConfig
from unskein.parsers.models import ParseResult, WarningCode
from unskein.parsers.python_parser import ProjectIndex, PythonAdapter

MakeProject = Callable[[dict[str, str]], Path]
SLOW_FILE = "slow.py"


class PoolLog:
    """Record what a fake pool was asked to do.

    Attributes:
        initializers: Arguments of every initializer call.
        submitted: Positional arguments of every submit.
        in_flight_files: Files submitted and not yet collected.
        max_in_flight_files: Highest value ``in_flight_files`` reached.
    """

    def __init__(self) -> None:
        self.initializers: list[tuple[Any, ...]] = []
        self.submitted: list[tuple[Any, ...]] = []
        self.in_flight_files = 0
        self.max_in_flight_files = 0


class LazyFuture(Future):
    """A future that runs its work when collected and can simulate a timeout."""

    def __init__(self, work: Callable[[], Any], file_count: int, is_stuck: bool, log: PoolLog):
        super().__init__()
        self._work = work
        self._file_count = file_count
        self._is_stuck = is_stuck
        self._log = log

    def result(self, timeout: float | None = None) -> Any:
        self._log.in_flight_files -= self._file_count
        self._file_count = 0
        if self._is_stuck:
            raise TimeoutError
        if not self.done():
            self.set_result(self._work())
        return super().result()


def install_fake_pool(monkeypatch: pytest.MonkeyPatch, *, is_broken: bool = False) -> PoolLog:
    """Replace ProcessPoolExecutor in the pipeline with an in-process fake.

    The initializer runs once per fake pool, as it does once per real worker.
    A batch holding ``SLOW_FILE`` never completes, as a stuck worker would.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        is_broken: Whether every submit fails as if a worker had died.

    Returns:
        The log the fake pool writes to.
    """
    log = PoolLog()
    monkeypatch.setattr(pipeline, "_worker_adapter", None)
    monkeypatch.setattr(pipeline, "_worker_shared", None)

    class FakePool:
        def __init__(self, max_workers=None, initializer=None, initargs=()):
            log.initializers.append(initargs)
            initializer(*initargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def submit(self, function, *args):
            if is_broken:
                raise BrokenProcessPool
            log.submitted.append(args)
            (batch,) = args
            log.in_flight_files += len(batch)
            log.max_in_flight_files = max(log.max_in_flight_files, log.in_flight_files)
            is_stuck = any(path.name == SLOW_FILE for path, _ in batch)
            return LazyFuture(lambda: function(*args), len(batch), is_stuck, log)

    monkeypatch.setattr(pipeline, "ProcessPoolExecutor", FakePool)
    return log


def module_files(root: Path, count: int) -> list[Path]:
    """Return the paths of the ``count`` modules made by ``chain_project``.

    Args:
        root: Project root.
        count: Number of modules.

    Returns:
        Their file paths, in module order.
    """
    return [root / f"pkg/m{i:03d}.py" for i in range(count)]


def chain_project(make_project: MakeProject, count: int) -> Path:
    """Write a package whose modules import their predecessor.

    Args:
        make_project: Fixture that writes files under a temporary root.
        count: Number of modules.

    Returns:
        The project root.
    """
    files = {"pkg/__init__.py": ""}
    for i in range(count):
        files[f"pkg/m{i:03d}.py"] = f"from pkg import m{i - 1:03d}\n" if i else "import os\n"
    return make_project(files)


def parallel_config(**overrides: Any) -> AnalysisConfig:
    """Return a config that always parallelizes, with two workers.

    Args:
        **overrides: Settings to change.

    Returns:
        The analysis config.
    """
    return AnalysisConfig(parallel_threshold=1, max_workers=2, **overrides)


@pytest.mark.parametrize(
    ("task_count", "workers", "queue_maxsize", "expected"),
    [
        (1, 4, 200, 1),
        (100, 4, 200, 6),
        (10_000, 4, 200, 32),
        (10_000, 4, 8, 8),
        (0, 4, 200, 1),
    ],
)
def test_batch_size_balances_workers_within_the_limits(
    task_count: int, workers: int, queue_maxsize: int, expected: int
) -> None:
    assert pipeline.batch_size(task_count, workers, queue_maxsize) == expected


def test_real_pool_gives_the_sequential_result_in_the_same_order(
    make_project: MakeProject,
) -> None:
    root = chain_project(make_project, 60)
    (root / "pkg" / "broken.py").write_text("def (:\n", encoding="utf-8")
    files = sorted(root.rglob("*.py"))
    adapter = PythonAdapter(parallel_config())

    parallel = pipeline.parse_all(files, adapter, root, adapter.config)

    assert parallel == adapter.parse(files, root)
    assert [w.code for w in parallel.warnings] == [WarningCode.PARSE_ERROR]


def test_index_travels_once_per_worker_and_never_with_a_task(
    make_project: MakeProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = chain_project(make_project, 40)
    log = install_fake_pool(monkeypatch)
    adapter = PythonAdapter(parallel_config())

    pipeline.parse_all(module_files(root, 40), adapter, root, adapter.config)

    assert len(log.initializers) == 1
    assert any(isinstance(arg, ProjectIndex) for arg in log.initializers[0])
    assert log.submitted
    for (batch,) in log.submitted:
        assert all(isinstance(path, Path) and isinstance(name, str) for path, name in batch)


def test_files_in_flight_never_exceed_queue_maxsize(
    make_project: MakeProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = chain_project(make_project, 60)
    log = install_fake_pool(monkeypatch)
    adapter = PythonAdapter(parallel_config(queue_maxsize=10))

    pipeline.parse_all(module_files(root, 60), adapter, root, adapter.config)

    assert 0 < log.max_in_flight_files <= 10


def test_fake_pool_result_matches_sequential(
    make_project: MakeProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = chain_project(make_project, 30)
    install_fake_pool(monkeypatch)
    adapter = PythonAdapter(parallel_config(queue_maxsize=8))
    files = module_files(root, 30)

    assert pipeline.parse_all(files, adapter, root, adapter.config) == adapter.parse(files, root)


def test_only_the_stuck_file_is_reported_when_its_batch_times_out(
    make_project: MakeProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = chain_project(make_project, 20)
    slow = root / "pkg" / SLOW_FILE
    slow.write_text("import os\n", encoding="utf-8")
    install_fake_pool(monkeypatch)
    adapter = PythonAdapter(parallel_config(per_file_timeout_seconds=7))
    files = [*module_files(root, 20), slow]

    result = pipeline.parse_all(files, adapter, root, adapter.config)

    assert [(w.code, w.path, w.detail) for w in result.warnings] == [
        (WarningCode.PARSE_TIMEOUT, slow, "7")
    ]
    assert len(result.modules) == 20


def test_dead_worker_falls_back_to_sequential_parsing(
    make_project: MakeProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = chain_project(make_project, 10)
    install_fake_pool(monkeypatch, is_broken=True)
    adapter = PythonAdapter(parallel_config())
    files = module_files(root, 10)

    result = pipeline.parse_all(files, adapter, root, adapter.config)

    assert result == adapter.parse(files, root)


def test_below_the_threshold_no_pool_is_created(
    make_project: MakeProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = chain_project(make_project, 5)
    log = install_fake_pool(monkeypatch)
    adapter = PythonAdapter(AnalysisConfig(parallel_threshold=50))

    result = pipeline.parse_all(module_files(root, 5), adapter, root, adapter.config)

    assert isinstance(result, ParseResult)
    assert log.initializers == []
