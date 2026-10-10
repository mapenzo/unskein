"""Markdown report of an untangle plan."""

from pathlib import Path

from unskein.graph.coupling import CouplingMetrics
from unskein.graph.proof import CutProof, ProbeResult, ProofResult, ProofVerdict, RunProof
from unskein.graph.steps import STEP_COSTS
from unskein.graph.untangle import Cut, ModuleChange, TanglePlan, UntanglePlan
from unskein.i18n import Lang, t

MAX_CUTS_SHOWN = 30
MAX_CHANGES_SHOWN = 15
MAX_MEMBERS_SHOWN = 10
MAX_SYMBOLS_SHOWN = 3
MAX_REGRESSIONS_SHOWN = 10
PROOF_SEPARATOR = " — "
PROOF_COLUMN = "untangle.col.proof"
NO_EVIDENCE_TEXT = "—"


def render_untangle(
    plan: UntanglePlan,
    root: Path,
    lang: Lang,
    *,
    max_tangles: int,
    proof: ProofResult | None = None,
) -> str:
    """Render an untangle plan as Markdown.

    Args:
        plan: The plan.
        root: Project root; names the report and makes evidence paths relative.
        lang: Report language.
        max_tangles: How many tangles to detail, largest first.
        proof: The proof of the plan; adds a column per cut, the proof summary, the run
            and the verdict legend. None leaves the report as it is without a proof.

    Returns:
        The report.
    """
    scope = "untangle.scope.all" if plan.all_edges else "untangle.scope.import"
    lines = [f"# {t('untangle.title', lang, project=root.resolve().name)}", "", t(scope, lang), ""]
    if plan.warnings:
        lines += [t("untangle.warnings", lang, count=plan.warnings), ""]
    if not plan.tangles:
        lines.append(t("untangle.none_all" if plan.all_edges else "untangle.none", lang))
        if plan.hidden_tangles and not plan.all_edges:
            lines += ["", t("untangle.hidden_hint", lang, count=plan.hidden_tangles)]
        return "\n".join(lines) + "\n"
    lines += _summary(plan, lang)
    if proof is not None:
        lines += ["", *_proof_summary(proof, lang)]
    if plan.hidden_tangles and not plan.all_edges:
        lines += ["", t("untangle.hidden_hint", lang, count=plan.hidden_tangles)]
    proofs = {(cut.source, cut.target): cut for cut in proof.cuts} if proof is not None else None
    shown = plan.tangles[:max_tangles]
    for index, tangle in enumerate(shown, start=1):
        lines += ["", *_tangle(tangle, index, root, lang, proofs=proofs)]
    if len(plan.tangles) > len(shown):
        lines += [
            "",
            t("untangle.tangles_truncated", lang, shown=len(shown), total=len(plan.tangles)),
        ]
    lines += ["", *_changes(plan.simulation.changes, lang)]
    lines += ["", *_steps_legend(plan, lang)]
    if proof is not None:
        lines += ["", *_proof_legend(lang)]
    return "\n".join(lines) + "\n"


def _count(value: int, truncated: bool) -> str:
    """Render a count, marked with ``+`` when the search stopped at its limit.

    Args:
        value: The count.
        truncated: Whether it is a lower bound.

    Returns:
        The count as text.
    """
    return f"{value}{'+' if truncated else ''}"


def _summary(plan: UntanglePlan, lang: Lang) -> list[str]:
    """Build the summary: how many cuts undo everything, and the simulation.

    Args:
        plan: The plan.
        lang: Report language.

    Returns:
        Markdown lines.
    """
    simulation = plan.simulation
    cuts = sum(len(tangle.cuts) for tangle in plan.tangles)
    cost = sum(tangle.cost for tangle in plan.tangles)
    return [
        t("untangle.summary", lang, tangles=len(plan.tangles), cuts=cuts, cost=cost),
        "",
        t(
            "untangle.simulation",
            lang,
            tangles_before=simulation.tangles_before,
            cycles_before=_count(simulation.cycles_before, simulation.cycles_before_truncated),
            tangles_after=simulation.tangles_after,
            cycles_after=_count(simulation.cycles_after, simulation.cycles_after_truncated),
        ),
        "",
        t("untangle.note", lang),
    ]


def _tangle(
    tangle: TanglePlan,
    index: int,
    root: Path,
    lang: Lang,
    *,
    proofs: dict[tuple[str, str], CutProof] | None,
) -> list[str]:
    """Build one tangle's section: its members and its cuts.

    Args:
        tangle: The tangle's plan.
        index: Position in the report, from 1.
        root: Project root, for relative paths.
        lang: Report language.
        proofs: The verdict of each cut, or None when the plan was not proven.

    Returns:
        Markdown lines.
    """
    members = ", ".join(f"`{m}`" for m in tangle.members[:MAX_MEMBERS_SHOWN])
    hidden = len(tangle.members) - MAX_MEMBERS_SHOWN
    if hidden > 0:
        members += f" {t('report.more', lang, count=hidden)}"
    lines = [
        f"## {t('untangle.tangle_heading', lang, index=index, size=len(tangle.members))}",
        "",
        t("untangle.tangle_line", lang, cuts=len(tangle.cuts), cost=tangle.cost, members=members),
        "",
        f"| {t('untangle.col.import', lang)} | {t('untangle.col.step', lang)} "
        f"| {t('untangle.col.cost', lang)} | {t('untangle.col.evidence', lang)}"
        f"{f' | {t(PROOF_COLUMN, lang)}' if proofs is not None else ''} |",
        "|---|---|---|---|" + ("---|" if proofs is not None else ""),
    ]
    lines += [
        _cut_row(
            cut, root, lang, proof=None if proofs is None else proofs.get((cut.source, cut.target))
        )
        for cut in tangle.cuts[:MAX_CUTS_SHOWN]
    ]
    if len(tangle.cuts) > MAX_CUTS_SHOWN:
        lines += ["", t("untangle.cuts_truncated", lang, count=len(tangle.cuts) - MAX_CUTS_SHOWN)]
    return lines


def _cut_row(cut: Cut, root: Path, lang: Lang, *, proof: CutProof | None = None) -> str:
    """Render one cut as a table row.

    Args:
        cut: The cut.
        root: Project root, for relative paths.
        lang: Report language.
        proof: The cut's verdict; adds the proof cell when given.

    Returns:
        One Markdown table row.
    """
    cells = [
        f"`{cut.source}` → `{cut.target}`",
        t(f"untangle.step.{cut.step}", lang),
        str(STEP_COSTS[cut.step]),
        _evidence(cut, root),
    ]
    if proof is not None:
        cells.append(_proof_cell(proof, lang))
    return "| " + " | ".join(cells) + " |"


def _evidence(cut: Cut, root: Path) -> str:
    """Render where a cut's import is and what it brings in.

    Args:
        cut: The cut.
        root: Project root, for relative paths.

    Returns:
        ``path:lines`` and up to ``MAX_SYMBOLS_SHOWN`` symbols, or a dash without evidence.
    """
    evidence = cut.evidence
    if evidence.file_path is None or not evidence.lines:
        return NO_EVIDENCE_TEXT
    try:
        path = evidence.file_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        path = evidence.file_path.as_posix()
    location = f"`{path}:{','.join(str(line) for line in evidence.lines)}`"
    symbols = [f"`{s}`" for s in evidence.symbols[:MAX_SYMBOLS_SHOWN]]
    if len(evidence.symbols) > MAX_SYMBOLS_SHOWN:
        symbols.append("…")
    return " · ".join([location, ", ".join(symbols)]) if symbols else location


def _changes(changes: tuple[ModuleChange, ...], lang: Lang) -> list[str]:
    """Build the table of the modules whose coupling changes the most.

    Args:
        changes: Coupling changes, largest instability change first.
        lang: Report language.

    Returns:
        Markdown lines.
    """
    lines = [
        f"## {t('untangle.changes_heading', lang)}",
        "",
        f"| {t('untangle.col.module', lang)} | Ca | Ce | {t('untangle.col.instability', lang)} |",
        "|---|---|---|---|",
    ]
    for change in changes[:MAX_CHANGES_SHOWN]:
        lines.append(f"| `{change.module}` | {_pair(change.before, change.after)} |")
    if len(changes) > MAX_CHANGES_SHOWN:
        lines += ["", t("report.more", lang, count=len(changes) - MAX_CHANGES_SHOWN)]
    return lines


def _pair(before: CouplingMetrics, after: CouplingMetrics) -> str:
    """Render Ca, Ce and instability as ``before → after`` cells.

    Args:
        before: Coupling before the cuts.
        after: Coupling after them.

    Returns:
        Three Markdown cells joined by `` | ``.
    """
    return " | ".join(
        [
            f"{before.afferent} → {after.afferent}",
            f"{before.efferent} → {after.efferent}",
            f"{before.instability:.2f} → {after.instability:.2f}",
        ]
    )


def _steps_legend(plan: UntanglePlan, lang: Lang) -> list[str]:
    """Explain each step used in the plan, cheapest first.

    Args:
        plan: The plan.
        lang: Report language.

    Returns:
        Markdown lines.
    """
    used = {cut.step for tangle in plan.tangles for cut in tangle.cuts}
    lines = [f"## {t('untangle.steps_heading', lang)}", ""]
    for step in sorted(used, key=lambda kind: (STEP_COSTS[kind], kind)):
        lines.append(
            f"- **{t(f'untangle.step.{step}', lang)}**: {t(f'untangle.step.{step}.help', lang)}"
        )
    return lines


def _proof_cell(proof: CutProof, lang: Lang) -> str:
    """Render a cut's verdict, its reason and, for a failed import, the evidence.

    Args:
        proof: The cut's verdict.
        lang: Report language.

    Returns:
        The table cell, safe inside a Markdown table.
    """
    cell = t(f"untangle.proof.{proof.verdict}", lang)
    if proof.reason is not None:
        cell += PROOF_SEPARATOR + t(f"untangle.proof.reason.{proof.reason}", lang)
    if proof.detail:
        cell += f" ({proof.detail.replace('|', chr(92) + '|')})"
    return cell


def _proof_summary(proof: ProofResult, lang: Lang) -> list[str]:
    """Build the proof summary and, with ``--run``, the import check.

    Args:
        proof: The proof of the plan.
        lang: Report language.

    Returns:
        Markdown lines.
    """
    lines = [
        t(
            "untangle.proof.summary",
            lang,
            proven=proof.count(ProofVerdict.PROVEN),
            total=len(proof.cuts),
            not_proven=proof.count(ProofVerdict.NOT_PROVEN),
            broken=proof.count(ProofVerdict.BROKEN),
            tangles=proof.tangles_after,
            cycles=_count(proof.cycles_after, proof.cycles_after_truncated),
        )
    ]
    if proof.run is not None:
        lines += ["", *_run_lines(proof.run, lang)]
    return lines


def _run_lines(run: RunProof, lang: Lang) -> list[str]:
    """Build the import check: its summary, the execution warning and the regressions.

    Args:
        run: The execution layer of the proof.
        lang: Report language.

    Returns:
        Markdown lines.
    """
    lines = [
        t(
            "untangle.proof.run",
            lang,
            seconds=f"{run.seconds:.1f}",
            importable=run.importable,
            modules=run.modules,
            regressions=len(run.regressions) + len(run.unattributed),
        ),
        "",
        t("untangle.proof.run_warning", lang),
    ]
    if run.regressions:
        lines.append("")
        lines += _regression_bullets(run.regressions, lang)
    if run.unattributed:
        lines += ["", t("untangle.proof.unattributed", lang, count=len(run.unattributed)), ""]
        lines += _regression_bullets(run.unattributed, lang)
    return lines


def _regression_bullets(failed: tuple[ProbeResult, ...], lang: Lang) -> list[str]:
    """List failed imports, capped.

    Args:
        failed: Modules that stopped importing.
        lang: Report language.

    Returns:
        Markdown bullet lines.
    """
    lines = [
        f"- {t('untangle.proof.regression', lang, module=result.module, error=result.error)}"
        for result in failed[:MAX_REGRESSIONS_SHOWN]
    ]
    if len(failed) > MAX_REGRESSIONS_SHOWN:
        lines.append(f"- {t('report.more', lang, count=len(failed) - MAX_REGRESSIONS_SHOWN)}")
    return lines


def _proof_legend(lang: Lang) -> list[str]:
    """Explain each verdict of the proof.

    Args:
        lang: Report language.

    Returns:
        Markdown lines.
    """
    lines = [f"## {t('untangle.proof.legend', lang)}", ""]
    for verdict in ProofVerdict:
        label = t(f"untangle.proof.{verdict}", lang)
        lines.append(f"- **{label}**: {t(f'untangle.proof.legend.{verdict}', lang)}")
    return lines
