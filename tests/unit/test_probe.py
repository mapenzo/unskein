import sys
from pathlib import Path

from unskein.probe import ProbeJob, import_roots, run_probes


def job(root: Path, *roots: Path, timeout: float = 30) -> ProbeJob:
    return ProbeJob(Path(sys.executable), root, roots or (root,), timeout, workers=2)


def test_a_module_that_imports_is_ok(tmp_path: Path) -> None:
    (tmp_path / "good.py").write_text("X = 1\n")
    result = run_probes(job(tmp_path), ["good"])["good"]
    assert result.ok and result.error == ""


def test_a_failing_import_reports_the_last_error_line_and_the_files(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("raise RuntimeError('boom')\n")
    result = run_probes(job(tmp_path), ["bad"])["bad"]
    assert not result.ok
    assert result.error == "RuntimeError: boom"
    assert any(f.endswith("bad.py") for f in result.files)


def test_a_slow_import_times_out(tmp_path: Path) -> None:
    (tmp_path / "slow.py").write_text("import time\ntime.sleep(30)\n")
    result = run_probes(job(tmp_path, timeout=1), ["slow"])["slow"]
    assert not result.ok and result.error == "timeout"


def test_each_module_runs_in_its_own_process(tmp_path: Path) -> None:
    (tmp_path / "first.py").write_text("import sys\nsys.marker = 1\n")
    (tmp_path / "second.py").write_text("import sys\nassert not hasattr(sys, 'marker')\n")
    results = run_probes(job(tmp_path), ["first", "second"])
    assert results["first"].ok and results["second"].ok


def test_the_project_is_not_importable_by_accident_from_the_working_directory(
    tmp_path: Path,
) -> None:
    other = tmp_path / "elsewhere"
    other.mkdir()
    (tmp_path / "mod.py").write_text("X = 1\n")
    assert not run_probes(ProbeJob(Path(sys.executable), tmp_path, (other,), 30, 1), ["mod"])[
        "mod"
    ].ok


def test_import_roots_strip_the_module_path() -> None:
    modules = {
        "pk.a": Path("src/pk/a.py"),
        "pk": Path("src/pk/__init__.py"),
        "top": Path("top.py"),
    }
    assert import_roots(modules, Path("/c")) == (Path("/c"), Path("/c/src"))
