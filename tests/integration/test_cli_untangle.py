from collections.abc import Callable
from pathlib import Path

from typer.testing import CliRunner

from unskein.cli import app
from unskein.errors import ExitCode

runner = CliRunner()
MakeProject = Callable[[dict[str, str]], Path]

CYCLE = {
    "app/__init__.py": "",
    "app/a.py": "from app.b import helper\n\nVALUE = helper()\n",
    "app/b.py": "from app.a import VALUE\n\n\ndef helper():\n    return 1\n\n\n"
    "def show():\n    return VALUE\n",
}


def test_untangle_prints_the_plan_and_exits_ok(make_project: MakeProject) -> None:
    root = make_project(CYCLE)
    result = runner.invoke(app, ["untangle", str(root), "--lang", "en"])
    assert result.exit_code == ExitCode.OK
    assert "Untangle plan for" in result.output
    assert "app.b" in result.output and "Lazy import" in result.output


def test_untangle_writes_the_raw_markdown(make_project: MakeProject, tmp_path: Path) -> None:
    root = make_project(CYCLE)
    out = tmp_path / "plan.md"
    result = runner.invoke(app, ["untangle", str(root), "--lang", "es", "-o", str(out)])
    assert result.exit_code == ExitCode.OK
    assert out.read_text(encoding="utf-8").startswith("# Plan de desenredo de ")


def test_untangle_all_edges_includes_hidden_coupling(make_project: MakeProject) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/a.py": "from app.b import B, C, D\n\nx = (B(), C(), D())\n",
            "app/b.py": "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n"
            "    from app.a import x\n\nclass B: ...\nclass C: ...\nclass D: ...\n",
        }
    )
    plain = runner.invoke(app, ["untangle", str(root), "--lang", "en"])
    assert "No import-time tangles" in plain.output
    everything = runner.invoke(app, ["untangle", str(root), "--lang", "en", "--all-edges"])
    assert everything.exit_code == ExitCode.OK
    assert "Tangle 1: 2 modules" in everything.output


def test_untangle_missing_path_exits_1(tmp_path: Path) -> None:
    result = runner.invoke(app, ["untangle", str(tmp_path / "nope"), "--lang", "en"])
    assert result.exit_code == ExitCode.USAGE_ERROR


def test_untangle_rejects_a_non_positive_max_tangles(make_project: MakeProject) -> None:
    root = make_project(CYCLE)
    result = runner.invoke(app, ["untangle", str(root), "--max-tangles", "0"])
    assert result.exit_code != ExitCode.OK


def test_untangle_reports_skipped_files(make_project: MakeProject) -> None:
    root = make_project({**CYCLE, "app/broken.py": "def broken(:\n"})
    result = runner.invoke(app, ["untangle", str(root), "--lang", "en"])
    assert result.exit_code == ExitCode.OK
    assert "Analysis warnings: 1" in result.output
