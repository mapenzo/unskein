from collections.abc import Callable
from pathlib import Path

import pytest

from unskein import prove as prove_module
from unskein.graph.proof import ProofReason, ProofVerdict
from unskein.graph.steps import StepKind
from unskein.parsers.rewrite import Rewritten
from unskein.proof_facts import ProjectFacts
from unskein.prove import ProofUnavailable, ProveOptions, prove_plan
from unskein.untangle import UntangleOptions, build_untangle_plan, prepare_untangle

MakeProject = Callable[[dict[str, str]], Path]

LAZY_CYCLE = {
    "app/__init__.py": "",
    "app/a.py": "from app.b import helper\n\nVALUE = helper()\n",
    "app/b.py": (
        "from app.a import VALUE\n\n\ndef helper():\n    return 1\n\n\n"
        "def show():\n    return VALUE\n"
    ),
}
BYPASS_BY_SYMBOL = {
    "app/__init__.py": "from .errors import Boom\nfrom .user import ERRORS\n",
    "app/errors.py": "class Boom(Exception):\n    pass\n",
    "app/user.py": "import app\n\nERRORS = (app.Boom,)\n\n\ndef use():\n    return app\n",
}
WHOLE_FACADE = {
    "pkg/__init__.py": "from .a import run\n\nsetting = 1\n",
    "pkg/a.py": (
        "import pkg\n\n\ndef run():\n    return pkg.setting\n\n\ndef whole():\n    return pkg\n"
    ),
}

POSTPONE_CYCLE = {
    "app/__init__.py": "",
    "app/a.py": "from app.b import B\n\n\ndef make() -> B:\n    return B()\n",
    "app/b.py": (
        "from app.a import make\n\n\nclass B:\n    pass\n\n\ndef again():\n    return make()\n"
    ),
}


def make_project_in(base: Path, files: dict[str, str]) -> Path:
    for rel, source in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return base


def prove(root: Path, *, all_edges: bool = False):
    context = prepare_untangle(UntangleOptions(path=root, all_edges=all_edges), env={})
    plan = build_untangle_plan(context, all_edges=all_edges)
    return plan, prove_plan(context, plan, ProveOptions())


def test_a_lazy_cut_is_proven(make_project: MakeProject) -> None:
    plan, proof = prove(make_project(LAZY_CYCLE))
    [cut] = proof.cuts
    assert (cut.source, cut.target) == ("app.b", "app.a")
    assert cut.verdict is ProofVerdict.PROVEN
    assert (proof.tangles_after, proof.cycles_after) == (0, 0)


def test_the_user_project_is_never_modified(make_project: MakeProject) -> None:
    root = make_project(LAZY_CYCLE)
    before = {p: p.read_bytes() for p in root.rglob("*.py")}
    prove(root)
    assert {p: p.read_bytes() for p in root.rglob("*.py")} == before


def test_a_cut_that_needs_design_is_not_proven(make_project: MakeProject) -> None:
    files = {
        "app/__init__.py": "",
        "app/a.py": "from app.b import B\n\nX = B()\n",
        "app/b.py": "from app.a import X\n\n\nclass B:\n    y = X\n",
    }
    _, proof = prove(make_project(files))
    assert {(c.verdict, c.reason) for c in proof.cuts} == {
        (ProofVerdict.NOT_PROVEN, ProofReason.NEEDS_DESIGN)
    }


def test_a_cut_the_rewriter_refuses_carries_its_reason(make_project: MakeProject) -> None:
    files = {
        "app/__init__.py": "",
        "app/a.py": (
            "from app.b import helper\n\n__all__ = ['helper']\n\n\ndef g():\n    return helper()\n"
        ),
        "app/b.py": "from app.a import g\n\nVALUE = g\n\n\ndef helper():\n    return 1\n",
    }
    _, proof = prove(make_project(files))
    assert {(c.verdict, c.reason) for c in proof.cuts} == {
        (ProofVerdict.NOT_PROVEN, ProofReason.EXPORTED)
    }


def test_every_cut_of_the_plan_gets_a_verdict(make_project: MakeProject) -> None:
    plan, proof = prove(make_project(LAZY_CYCLE))
    planned = [(c.source, c.target) for t in plan.tangles for c in t.cuts]
    assert [(c.source, c.target) for c in proof.cuts] == planned


def test_a_rewrite_that_leaves_the_edge_is_broken(
    make_project: MakeProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    def untouched(source, moves):
        return Rewritten(source, (None,) * len(moves))

    monkeypatch.setattr(prove_module, "rewrite_source", untouched)
    _, proof = prove(make_project(LAZY_CYCLE))
    [cut] = proof.cuts
    assert (cut.verdict, cut.reason) == (ProofVerdict.BROKEN, ProofReason.EDGE_REMAINS)


def test_several_cuts_in_one_file_are_applied_together(make_project: MakeProject) -> None:
    files = {
        "app/__init__.py": "",
        "app/m.py": "from app.x import V\nfrom app.y import W\n\n\ndef f():\n    return V, W\n",
        "app/x.py": "from app.m import f\n\nV = f\n",
        "app/y.py": "from app.m import f\n\nW = f\n",
    }
    plan, proof = prove(make_project(files))
    assert sorted((c.source, c.target) for c in proof.cuts) == [
        ("app.m", "app.x"),
        ("app.m", "app.y"),
    ]
    assert proof.count(ProofVerdict.PROVEN) == 2
    assert proof.tangles_after == 0


def edited_copy(root: Path, tmp_path: Path) -> Path:
    context = prepare_untangle(UntangleOptions(path=root), env={})
    plan = build_untangle_plan(context, all_edges=False)
    copy_root = tmp_path / "copy"
    prove_module.copy_project(context, copy_root)
    cuts = [cut for tangle in plan.tangles for cut in tangle.cuts]
    applied, _ = prove_module._apply_cuts(context, cuts, copy_root, facts=ProjectFacts(context))
    assert len(applied) == 1
    return copy_root


def test_crlf_and_bom_survive_the_edit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    root = make_project_in(project, LAZY_CYCLE)
    (root / "app" / "b.py").write_bytes(
        (
            "\ufeffimport os\r\nfrom app.a import VALUE\r\n\r\n\r\ndef helper():\r\n    return 1"
            "\r\n\r\n\r\ndef show():\r\n    return VALUE\r\n"
        ).encode("utf-8")
    )
    data = (edited_copy(root, tmp_path) / "app" / "b.py").read_bytes()
    assert data.startswith(b"\xef\xbb\xbfimport os\r\n")
    assert b"def show():\r\n    from app.a import VALUE\r\n    return VALUE\r\n" in data
    assert data.count(b"\n") == data.count(b"\r\n")


def test_a_declared_encoding_survives_the_edit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    root = make_project_in(project, LAZY_CYCLE)
    second = "# -*- coding: latin-1 -*-\n" + LAZY_CYCLE["app/b.py"] + "NAME = 'caf\xe9'\n"
    (root / "app" / "b.py").write_bytes(second.encode("latin-1"))
    data = (edited_copy(root, tmp_path) / "app" / "b.py").read_bytes()
    assert b"NAME = 'caf\xe9'" in data
    assert b"    from app.a import VALUE\n" in data


def test_a_copy_failure_is_reported_as_unavailable(
    make_project: MakeProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(prove_module.shutil, "copy2", fail)
    with pytest.raises(ProofUnavailable):
        prove(make_project(LAZY_CYCLE))


def test_a_whole_module_facade_import_read_in_functions_is_proven_lazy(
    make_project: MakeProject,
) -> None:
    plan, proof = prove(make_project(WHOLE_FACADE))
    [cut] = plan.tangles[0].cuts
    assert cut.step is StepKind.LAZY
    assert [(p.verdict, p.reason) for p in proof.cuts] == [(ProofVerdict.PROVEN, None)]
    assert proof.tangles_after == 0


def test_an_evaluated_annotation_cut_is_proven_by_postponing_annotations(
    make_project: MakeProject,
) -> None:
    plan, proof = prove(make_project(POSTPONE_CYCLE))
    [cut] = plan.tangles[0].cuts
    assert (cut.source, cut.target, cut.step) == ("app.a", "app.b", StepKind.POSTPONE_ANNOTATIONS)
    assert [(p.verdict, p.reason) for p in proof.cuts] == [(ProofVerdict.PROVEN, None)]
    assert proof.tangles_after == 0


def test_an_import_time_read_through_the_facade_is_proven_by_a_direct_import(
    make_project: MakeProject,
) -> None:
    plan, proof = prove(make_project(BYPASS_BY_SYMBOL))
    [cut] = plan.tangles[0].cuts
    assert (cut.source, cut.target, cut.step) == ("app.user", "app", StepKind.BYPASS_FACADE)
    assert [(p.verdict, p.reason) for p in proof.cuts] == [(ProofVerdict.PROVEN, None)]
    assert proof.tangles_after == 0


def test_a_name_that_something_reassigns_is_not_bypassed(make_project: MakeProject) -> None:
    files = dict(BYPASS_BY_SYMBOL) | {"app/other.py": "import app\n\napp.Boom = None\n"}
    _, proof = prove(make_project(files))
    assert [(p.verdict, p.reason) for p in proof.cuts] == [
        (ProofVerdict.NOT_PROVEN, ProofReason.MUTABLE_ATTRIBUTE)
    ]
