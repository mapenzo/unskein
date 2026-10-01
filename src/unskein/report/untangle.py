"""Markdown report of an untangle plan."""

from pathlib import Path

from unskein.graph.coupling import CouplingMetrics
from unskein.graph.steps import STEP_COSTS
from unskein.graph.untangle import Cut, ModuleChange, TanglePlan, UntanglePlan
from unskein.i18n import Lang, t

MAX_CUTS_SHOWN = 30
MAX_CHANGES_SHOWN = 15
MAX_MEMBERS_SHOWN = 10
MAX_SYMBOLS_SHOWN = 3
NO_EVIDENCE_TEXT = "—"


def render_untangle(plan: UntanglePlan, root: Path, lang: Lang, *, max_tangles: int) -> str:
    """Render an untangle plan as Markdown.

    Args:
        plan: The plan.
        root: Project root; names the report and makes evidence paths relative.
        lang: Report language.
        max_tangles: How many tangles to detail, largest first.

    Returns:
        The report.
    """
    scope = "untangle.scope.all" if plan.all_edges else "untangle.scope.import"
    lines = [f"# {t('untangle.title', lang, project=root.resolve().name)}", "", t(scope, lang), ""]
    if not plan.tangles:
        lines.append(t("untangle.none_all" if plan.all_edges else "untangle.none", lang))
        if plan.hidden_tangles and not plan.all_edges:
            lines += ["", t("untangle.hidden_hint", lang, count=plan.hidden_tangles)]
        return "\n".join(lines) + "\n"
    lines += _summary(plan, lang)
    if plan.hidden_tangles and not plan.all_edges:
        lines += ["", t("untangle.hidden_hint", lang, count=plan.hidden_tangles)]
    shown = plan.tangles[:max_tangles]
    for index, tangle in enumerate(shown, start=1):
        lines += ["", *_tangle(tangle, index, root, lang)]
    if len(plan.tangles) > len(shown):
        lines += [
            "",
            t("untangle.tangles_truncated", lang, shown=len(shown), total=len(plan.tangles)),
        ]
    lines += ["", *_changes(plan.simulation.changes, lang)]
    lines += ["", *_steps_legend(plan, lang)]
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


def _tangle(tangle: TanglePlan, index: int, root: Path, lang: Lang) -> list[str]:
    """Build one tangle's section: its members and its cuts.

    Args:
        tangle: The tangle's plan.
        index: Position in the report, from 1.
        root: Project root, for relative paths.
        lang: Report language.

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
        f"| {t('untangle.col.cost', lang)} | {t('untangle.col.evidence', lang)} |",
        "|---|---|---|---|",
    ]
    lines += [_cut_row(cut, root, lang) for cut in tangle.cuts[:MAX_CUTS_SHOWN]]
    if len(tangle.cuts) > MAX_CUTS_SHOWN:
        lines += ["", t("untangle.cuts_truncated", lang, count=len(tangle.cuts) - MAX_CUTS_SHOWN)]
    return lines


def _cut_row(cut: Cut, root: Path, lang: Lang) -> str:
    """Render one cut as a table row.

    Args:
        cut: The cut.
        root: Project root, for relative paths.
        lang: Report language.

    Returns:
        One Markdown table row.
    """
    step = t(f"untangle.step.{cut.step}", lang)
    cost = STEP_COSTS[cut.step]
    return f"| `{cut.source}` → `{cut.target}` | {step} | {cost} | {_evidence(cut, root)} |"


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
