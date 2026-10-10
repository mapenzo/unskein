import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from unskein import prove as prove_module
from unskein.errors import UnskeinError
from unskein.graph.proof import ProofReason, ProofVerdict
from unskein.graph.steps import StepKind
from unskein.graph.untangle import Cut
from unskein.parsers.rewrite import Rewritten
from unskein.parsers.usage import NO_EVIDENCE
from unskein.prove import ProveOptions, prove_plan
from unskein.untangle import UntangleOptions, build_untangle_plan, prepare_untangle

MakeProject = Callable[[dict[str, str]], Path]

CYCLE_THAT_IMPORTS = {
    "app/__init__.py": "",
    "app/a.py": "import app.b\n\n\ndef fa():\n    return app.b.fb\n",
    "app/b.py": "import app.a\n\n\ndef fb():\n    return app.a.fa\n",
}


def prove_run(root: Path, **kwargs):
    context = prepare_untangle(UntangleOptions(path=root), env={})
    plan = build_untangle_plan(context, all_edges=False)
    return prove_plan(context, plan, ProveOptions(run=True, **kwargs))


def test_run_reports_modules_that_import_before_and_after(make_project: MakeProject) -> None:
    proof = prove_run(make_project(CYCLE_THAT_IMPORTS))
    assert proof.run is not None
    assert proof.run.modules == 2 and proof.run.importable == 2
    assert proof.run.regressions == () and proof.run.unattributed == ()
    assert [c.verdict for c in proof.cuts] == [ProofVerdict.PROVEN]


def test_a_module_broken_after_its_cut_marks_that_cut_broken(
    make_project: MakeProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = prove_module.rewrite_source

    def failing(source, moves):
        result = real(source, moves)
        return Rewritten(result.source + "\nraise RuntimeError('boom')\n", result.refusals)

    monkeypatch.setattr(prove_module, "rewrite_source", failing)
    proof = prove_run(make_project(CYCLE_THAT_IMPORTS))
    [cut] = proof.cuts
    assert (cut.verdict, cut.reason) == (ProofVerdict.BROKEN, ProofReason.IMPORT_FAILED)
    assert "boom" in cut.detail


def test_modules_that_never_imported_do_not_count_as_regressions(make_project: MakeProject) -> None:
    files = dict(CYCLE_THAT_IMPORTS)
    files["app/a.py"] = "import missing_dependency\n" + files["app/a.py"]
    proof = prove_run(make_project(files))
    assert proof.run is not None
    assert proof.run.importable < proof.run.modules
    assert proof.run.regressions == ()


def run_inputs(tmp_path: Path, edited: bool) -> prove_module._RunInputs:
    before, after = tmp_path / "before", tmp_path / "after"
    for root, text in ((before, "X = 1\n"), (after, "raise RuntimeError('boom')\n")):
        root.mkdir()
        (root / "m.py").write_text(text)
        (root / "dead.py").write_text("import missing_dependency\n")
    cut = Cut("m", "n", StepKind.LAZY, NO_EVIDENCE)
    return prove_module._RunInputs(
        python=Path(sys.executable),
        before_root=before,
        after_root=after,
        modules={"m": Path("m.py"), "dead": Path("dead.py")},
        members=["dead", "m"],
        edited={(after / "m.py").resolve(): [cut]} if edited else {},
        workers=2,
    )


def test_a_regression_through_an_edited_file_is_tied_to_its_cut(tmp_path: Path) -> None:
    run, broken = prove_module._run_layer(run_inputs(tmp_path, edited=True))
    assert [r.module for r in run.regressions] == ["m"]
    assert run.unattributed == ()
    assert run.importable == 1
    [verdict] = broken.values()
    assert verdict.reason is ProofReason.IMPORT_FAILED and "boom" in verdict.detail


def test_a_regression_through_no_edited_file_is_unattributed(tmp_path: Path) -> None:
    run, broken = prove_module._run_layer(run_inputs(tmp_path, edited=False))
    assert run.regressions == ()
    assert [r.module for r in run.unattributed] == ["m"]
    assert broken == {}


def test_a_missing_interpreter_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(UnskeinError):
        prove_module.resolve_python(tmp_path / "no-python")
    assert prove_module.resolve_python(None) == Path(sys.executable)


def test_the_run_copies_data_files_that_modules_read_when_imported(
    make_project: MakeProject,
) -> None:
    files = dict(CYCLE_THAT_IMPORTS)
    files["app/data.json"] = '{"a": 1}'
    files["app/a.py"] = (
        "import json\nimport pathlib\n\nimport app.b\n\n"
        "DATA = json.loads(pathlib.Path(__file__).with_name('data.json').read_text())\n\n\n"
        "def fa():\n    return app.b.fb\n"
    )
    proof = prove_run(make_project(files))
    assert proof.run is not None
    assert proof.run.importable == proof.run.modules == 2
    assert proof.run.regressions == () and proof.run.unattributed == ()
