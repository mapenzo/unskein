from collections.abc import Callable
from pathlib import Path

from unskein.graph.proof import (
    CutProof,
    ProbeResult,
    ProofReason,
    ProofResult,
    ProofVerdict,
    RunProof,
)
from unskein.graph.untangle import UntanglePlan
from unskein.i18n import Lang, t
from unskein.report.untangle import MAX_REGRESSIONS_SHOWN, render_untangle
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


def plan_of(root: Path) -> UntanglePlan:
    context = prepare_untangle(UntangleOptions(path=root), env={})
    return build_untangle_plan(context, all_edges=False)


def proof_of(
    verdict: ProofVerdict,
    reason: ProofReason | None = None,
    *,
    detail: str = "",
    run: RunProof | None = None,
) -> ProofResult:
    return ProofResult(
        cuts=(CutProof("app.b", "app.a", verdict, reason, detail),),
        tangles_after=0,
        cycles_after=0,
        cycles_after_truncated=False,
        run=run,
    )


def render(make_project: MakeProject, proof: ProofResult | None, lang: Lang = Lang.EN) -> str:
    root = make_project(LAZY_CYCLE)
    return render_untangle(plan_of(root), root, lang, max_tangles=5, proof=proof)


def test_a_proven_cut_shows_its_verdict_in_a_new_column(make_project: MakeProject) -> None:
    report = render(make_project, proof_of(ProofVerdict.PROVEN))
    assert f"| {t('untangle.col.proof', Lang.EN)} |" in report
    assert f"| {t('untangle.proof.proven', Lang.EN)} |" in report


def test_the_summary_counts_the_verdicts(make_project: MakeProject) -> None:
    report = render(make_project, proof_of(ProofVerdict.PROVEN))
    summary = t(
        "untangle.proof.summary",
        Lang.EN,
        proven=1,
        total=1,
        not_proven=0,
        broken=0,
        tangles=0,
        cycles=0,
    )
    assert summary in report


def test_a_not_proven_cut_shows_its_reason(make_project: MakeProject) -> None:
    proof = proof_of(ProofVerdict.NOT_PROVEN, ProofReason.NEEDS_DESIGN)
    report = render(make_project, proof)
    reason = t("untangle.proof.reason.needs_design", Lang.EN)
    assert f"{t('untangle.proof.not_proven', Lang.EN)} — {reason}" in report


def test_a_failed_import_shows_the_module_and_the_error(make_project: MakeProject) -> None:
    proof = proof_of(
        ProofVerdict.BROKEN, ProofReason.IMPORT_FAILED, detail="app.b: RuntimeError: a | b"
    )
    report = render(make_project, proof)
    assert "app.b: RuntimeError: a \\| b" in report


def test_without_a_proof_the_report_has_no_proof_column(make_project: MakeProject) -> None:
    report = render(make_project, None)
    assert t("untangle.col.proof", Lang.EN) not in report
    assert t("untangle.proof.summary", Lang.EN, **dict.fromkeys(SUMMARY_FIELDS, 0)) not in report


SUMMARY_FIELDS = ("proven", "total", "not_proven", "broken", "tangles", "cycles")


def run_proof(regressions: int = 0) -> RunProof:
    failed = tuple(
        ProbeResult(f"m{index}", False, f"Error {index}") for index in range(regressions)
    )
    return RunProof(modules=4, importable=3, regressions=failed, unattributed=(), seconds=1.5)


def test_a_run_shows_the_execution_warning_and_its_summary(make_project: MakeProject) -> None:
    report = render(make_project, proof_of(ProofVerdict.PROVEN, run=run_proof()))
    assert t("untangle.proof.run_warning", Lang.EN) in report
    run = t("untangle.proof.run", Lang.EN, seconds="1.5", importable=3, modules=4, regressions=0)
    assert run in report


def test_regressions_are_listed_and_capped(make_project: MakeProject) -> None:
    many = MAX_REGRESSIONS_SHOWN + 2
    proof = proof_of(ProofVerdict.PROVEN, run=run_proof(many))
    report = render(make_project, proof)
    assert t("untangle.proof.regression", Lang.EN, module="m0", error="Error 0") in report
    assert t("report.more", Lang.EN, count=2) in report
    assert f"m{many - 1}`" not in report


def test_the_report_is_translated(make_project: MakeProject) -> None:
    report = render(make_project, proof_of(ProofVerdict.PROVEN), Lang.ES)
    assert t("untangle.col.proof", Lang.ES) in report
    assert t("untangle.proof.proven", Lang.ES) in report


def test_the_legend_explains_the_verdicts(make_project: MakeProject) -> None:
    report = render(make_project, proof_of(ProofVerdict.PROVEN))
    assert t("untangle.proof.legend", Lang.EN) in report
    assert t("untangle.proof.legend.broken", Lang.EN) in report
