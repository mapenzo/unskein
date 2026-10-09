"""Markdown report combining the deterministic analysis and the optional AI report."""

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from unskein.ai.models import AIFailure, AIReport, Problem, Severity
from unskein.graph.distributions import EDGE_ARROW, LIST_SEPARATOR, DistributionSummary
from unskein.graph.findings import Evidence, Finding, FindingKind
from unskein.graph.metrics import HIGH_COUPLING_PERCENTILE, AnalysisResult
from unskein.graph.missing import FIX_IMPORT_FROM, PAIR_SEPARATOR
from unskein.graph.native import NativeModule
from unskein.graph.stars import ANY_READER, KIND_SELF, WildcardAction, WildcardFix
from unskein.i18n import Lang, t, translate_warning
from unskein.parsers.models import ParseWarning, VirtualKind, WarningCode

SEVERITY_ORDER: dict[Severity, int] = {"low": 0, "medium": 1, "high": 2}
MAX_MODULES_IN_TABLE = 15
TOP_COUPLED_SHARE = 100 - HIGH_COUPLING_PERCENTILE
MAX_WARNING_EXAMPLES = 5
MAX_TANGLE_MEMBERS_SHOWN = 10
MAX_HIDDEN_TANGLES_SHOWN = 10
MAX_FINDINGS_PER_KIND = 10
# Findings whose fix is meant to be copied are all listed.
UNCAPPED_FINDINGS = frozenset({FindingKind.WILDCARD_IMPORT})
MAX_PACKAGES_IN_TABLE = 15
MAX_NATIVE_IN_TABLE = 15
MAX_PACKAGE_EDGES_SHOWN = 10
MIN_PACKAGES_SHOWN = 2
NOT_MEASURED = "—"
# Ce of compiled code: its imports cannot be read.
UNKNOWN_VALUE = "?"
MARKER_KEYS = {
    VirtualKind.NAMESPACE: "report.namespace_marker",
    VirtualKind.COMPILED: "report.compiled_marker",
    VirtualKind.STUB: "report.stub_marker",
}
# Order of the virtual counts in the summary and the general metrics.
VIRTUAL_COUNT_KEYS = (
    (VirtualKind.NAMESPACE, "report.summary_namespaces", "report.metric.namespaces"),
    (VirtualKind.COMPILED, "report.summary_compiled", "report.metric.compiled"),
    (VirtualKind.STUB, "report.summary_stubs", "report.metric.stubs"),
)
MIN_DISTRIBUTIONS_SHOWN = 2
CYCLE_SEPARATOR = " ↔ "
DETAIL_SEPARATOR = "; "
PART_SEPARATOR = ", "
# Kinds whose line shows the uses behind an edge between a distribution and its target.
EDGE_FINDINGS = (
    FindingKind.UNDECLARED_DEPENDENCY,
    FindingKind.OPTIONAL_REQUIRED,
    FindingKind.UNPACKAGED_IMPORT,
)


class AIStatus(StrEnum):
    """Why the AI section looks the way it does; the section is never left blank.

    Attributes:
        PRESENT: An AI report is available.
        DISABLED: The user passed ``--no-ai``.
        NOT_CONFIGURED: No AI model is configured in any layer.
        FAILED: AI is configured but produced no report; see ``ReportContext.ai_failure``.
    """

    PRESENT = "present"
    DISABLED = "disabled"
    NOT_CONFIGURED = "not_configured"
    FAILED = "failed"


@dataclass(frozen=True)
class ReportContext:
    """Everything a report is rendered from.

    Attributes:
        root: Project root; names the report and makes warning paths relative.
        result: The deterministic analysis.
        ai_report: The AI interpretation, or None.
        ai_status: Why the AI section has, or lacks, content.
        min_severity: Lowest AI problem severity to show.
        ai_failure: Why the AI produced no report, when ai_status is FAILED.
        ai_error_type: Exception class name behind a call error.
        ai_dropped_problems: AI problems discarded for naming no known module.
    """

    root: Path
    result: AnalysisResult
    ai_report: AIReport | None
    ai_status: AIStatus
    min_severity: Severity = "low"
    ai_failure: AIFailure | None = None
    ai_error_type: str | None = None
    ai_dropped_problems: int = 0


def filter_by_severity(problems: list[Problem], min_severity: Severity) -> list[Problem]:
    """Keep problems at or above a severity threshold.

    Applied at presentation time so the LLM is never asked to filter.

    Args:
        problems: Problems flagged by the LLM.
        min_severity: Lowest severity to keep.

    Returns:
        Problems whose severity is at least ``min_severity``, in original order.
    """
    threshold = SEVERITY_ORDER[min_severity]
    return [p for p in problems if SEVERITY_ORDER[p.severity] >= threshold]


def render_report(context: ReportContext, lang: Lang) -> str:
    """Render the full report as Markdown.

    Formatting only, no business logic: every number and judgment comes from
    the analysis or the AI report. The warnings and scripts sections appear
    only when there are any; every other section is always present.

    Args:
        context: Analysis, AI report and presentation settings.
        lang: Language of the report text.

    Returns:
        The report as a Markdown string.
    """
    sections = [
        [f"# {t('report.title', lang, project=context.root.resolve().name)}"],
        _summary(context, lang),
        _metrics(context.result, lang),
        _cycles(context.result, lang),
    ]
    packages = _packages(context.result, lang)
    if packages:
        sections.append(packages)
    if _shows_distributions(context.result):
        sections.append(_distributions(context.result, lang))
    if context.result.scripts:
        sections.append(_scripts(context.result, lang))
    if context.result.native:
        sections.append(_native_boundary(context.result, lang))
    sections.append(_coupled(context.result, lang))
    if context.result.findings_enabled:
        sections.append(_findings(context.result, lang))
    sections.append(_ai(context, lang))
    if context.result.parse_warnings:
        sections.append(_warnings(context.result.parse_warnings, context.root, lang))
    return "\n\n".join("\n".join(lines) for lines in sections) + "\n"


def _module_count(result: AnalysisResult) -> int:
    """Return how many ``.py`` modules the graph has; virtual modules are counted apart.

    Args:
        result: The deterministic analysis.

    Returns:
        Nodes of the graph that are parsed files.
    """
    return result.graph.number_of_nodes() - len(result.virtual)


def _virtual_count(result: AnalysisResult, kind: VirtualKind) -> int:
    """Return how many graph nodes are virtual modules of one kind.

    Args:
        result: The deterministic analysis.
        kind: Kind to count.

    Returns:
        The count.
    """
    return sum(1 for found in result.virtual.values() if found is kind)


def _module_name(name: str, result: AnalysisResult, lang: Lang) -> str:
    """Render a module name, marked when it has no parsed file.

    Args:
        name: Dotted module name.
        result: The deterministic analysis.
        lang: Report language.

    Returns:
        The name in backticks, followed by the marker of its kind when it is virtual.
    """
    kind = result.virtual.get(name)
    if kind is not None:
        return f"`{name}` {t(MARKER_KEYS[kind], lang)}"
    return f"`{name}`"


def _efferent(name: str, result: AnalysisResult) -> str:
    """Render the Ce of a module; unknown for compiled code and stubs.

    Args:
        name: Dotted module name.
        result: The deterministic analysis.

    Returns:
        The count, or ``UNKNOWN_VALUE``.
    """
    kind = result.virtual.get(name)
    if kind is not None and kind.is_native:
        return UNKNOWN_VALUE
    return str(result.coupling_metrics[name].efferent)


def _instability(name: str, result: AnalysisResult) -> str:
    """Render the instability of a module; not measured when its Ce is unknown.

    Args:
        name: Dotted module name.
        result: The deterministic analysis.

    Returns:
        Two decimals, or ``NOT_MEASURED``.
    """
    kind = result.virtual.get(name)
    if kind is not None and kind.is_native:
        return NOT_MEASURED
    return f"{result.coupling_metrics[name].instability:.2f}"


def _plural_key(count: int, is_truncated: bool = False) -> str:
    """Return the catalog suffix for a count: ``one`` only for exactly one.

    Args:
        count: The number shown.
        is_truncated: Whether it is a lower bound (``100+``), always plural.

    Returns:
        ``"one"`` or ``"other"``.
    """
    return "one" if count == 1 and not is_truncated else "other"


def _counted(key_prefix: str, count: int, lang: Lang) -> str:
    """Render a count with its noun in the singular or the plural.

    Args:
        key_prefix: Catalog key without its ``.one``/``.other`` suffix.
        count: The number.
        lang: Report language.

    Returns:
        The count and its noun.
    """
    return t(f"{key_prefix}.{_plural_key(count)}", lang, count=count)


def _cycle_count(result: AnalysisResult) -> str:
    """Return the number of cycles, marked with ``+`` when the search was truncated.

    Args:
        result: The deterministic analysis.

    Returns:
        The count as text, e.g. ``"100+"``.
    """
    return f"{len(result.cycles)}{'+' if result.cycles_truncated else ''}"


def _summary(context: ReportContext, lang: Lang) -> list[str]:
    """Build the summary: always the key numbers, plus the AI summary when present.

    Args:
        context: Report context.
        lang: Report language.

    Returns:
        Markdown lines of the section.
    """
    result = context.result
    virtual = ""
    for kind, key_prefix, _ in VIRTUAL_COUNT_KEYS:
        count = _virtual_count(result, kind)
        if count:
            key = _plural_key(count)
            virtual += t(f"{key_prefix}.{key}", lang, count=count)
    scripts = ""
    if result.scripts:
        key = _plural_key(len(result.scripts))
        scripts = t(f"report.summary_scripts.{key}", lang, count=len(result.scripts))
    counts = t(
        "report.summary_counts",
        lang,
        modules=_counted("report.summary_modules", _module_count(result), lang),
        scripts=f"{virtual}{scripts}",
        dependencies=_counted("report.summary_dependencies", result.graph.number_of_edges(), lang),
        cycles=t(
            f"report.summary_cycles.{_plural_key(len(result.cycles), result.cycles_truncated)}",
            lang,
            count=_cycle_count(result),
        ),
    )
    lines = [f"## {t('report.summary', lang)}", "", counts]
    if result.high_coupling_modules:
        top = result.coupling_metrics[result.high_coupling_modules[0]]
        top_line = t(
            "report.summary_top_module",
            lang,
            module=_module_name(top.module, result, lang),
            ca=top.afferent,
            ce=_efferent(top.module, result),
        )
        lines.append(top_line)
    if result.tangles:
        lines.append(_tangle_summary(result.tangles, lang, "report.summary_tangles"))
        lines.append(t("report.untangle_hint", lang))
    if result.hidden_tangles:
        lines.append(_tangle_summary(result.hidden_tangles, lang, "report.summary_hidden"))
    if result.findings:
        key = _plural_key(len(result.findings))
        lines.append(t(f"report.summary_findings.{key}", lang, count=len(result.findings)))
    if _shows_distributions(result):
        blocked = sum(1 for summary in result.distributions if summary.installable is False)
        lines.append(
            t(
                "report.summary_distributions",
                lang,
                count=len(result.distributions),
                blocked=blocked,
            )
        )
    if context.ai_report:
        health = t(f"report.health.{context.ai_report.architecture_health}", lang)
        lines += ["", context.ai_report.summary, "", t("report.health", lang, health=health)]
    return lines


def _tangle_summary(tangles: list[list[str]], lang: Lang, key_prefix: str) -> str:
    """Summarize how many tangles there are and how big the largest one is.

    Args:
        tangles: Tangles of the analysis, largest first.
        lang: Report language.
        key_prefix: Catalog key without its ``.one``/``.other`` suffix.

    Returns:
        One sentence, singular or plural.
    """
    largest = len(tangles[0])
    if len(tangles) == 1:
        return t(f"{key_prefix}.one", lang, size=largest)
    return t(f"{key_prefix}.other", lang, count=len(tangles), size=largest)


def _metrics(result: AnalysisResult, lang: Lang) -> list[str]:
    """Build the general metrics table.

    Args:
        result: The deterministic analysis.
        lang: Report language.

    Returns:
        Markdown lines of the section.
    """
    rows = [("report.metric.modules", _module_count(result))]
    for kind, _, metric_key in VIRTUAL_COUNT_KEYS:
        count = _virtual_count(result, kind)
        if count:
            rows.append((metric_key, count))
    if result.scripts:
        rows.append(("report.metric.scripts", len(result.scripts)))
    rows += [
        ("report.metric.dependencies", result.graph.number_of_edges()),
        ("report.metric.cycles", _cycle_count(result)),
        ("report.metric.tangles", len(result.tangles)),
        ("report.metric.hidden_tangles", len(result.hidden_tangles)),
        ("report.metric.warnings", len(result.parse_warnings)),
    ]
    lines = [
        f"## {t('report.metrics', lang)}",
        "",
        f"| {t('report.metric', lang)} | {t('report.value', lang)} |",
        "|---|---|",
    ]
    lines += [f"| {t(key, lang)} | {value} |" for key, value in rows]
    return lines


def _cycles(result: AnalysisResult, lang: Lang) -> list[str]:
    """List the tangles first, then every cycle found as an example loop.

    Tangles give the true extent of the problem (never truncated); cycles,
    which can be truncated, illustrate concrete dependency paths inside them.
    Both exist at import time; coupling that appears only through lazy or
    type-only imports follows in its own subsection.

    Args:
        result: The deterministic analysis.
        lang: Report language.

    Returns:
        Markdown lines of the section.
    """
    lines = [f"## {t('report.cycles', lang)}", ""]
    if result.cycles:
        lines += [f"### {t('report.tangles_heading', lang)}", ""]
        lines += [_tangle_line(tangle, lang) for tangle in result.tangles]
        lines += ["", f"### {t('report.cycles_heading', lang)}", ""]
        for cycle in result.cycles:
            loop = [*cycle, cycle[0]]
            lines.append("- " + " → ".join(f"`{module}`" for module in loop))
        if result.cycles_truncated:
            lines += ["", t("report.cycles_truncated", lang, shown=len(result.cycles))]
    else:
        lines.append(t("report.no_cycles", lang))
    if result.hidden_tangles:
        lines += _hidden_coupling(result.hidden_tangles, lang)
    return lines


def _hidden_coupling(hidden_tangles: list[list[str]], lang: Lang) -> list[str]:
    """Build the subsection of tangles that exist only through lazy or type-only imports.

    Args:
        hidden_tangles: Hidden tangles of the analysis, largest first.
        lang: Report language.

    Returns:
        Markdown lines: heading, explanation and at most ``MAX_HIDDEN_TANGLES_SHOWN`` tangles.
    """
    shown = hidden_tangles[:MAX_HIDDEN_TANGLES_SHOWN]
    lines = [
        "",
        f"### {t('report.hidden_heading', lang)}",
        "",
        t("report.hidden_explanation", lang),
        "",
    ]
    lines += [_tangle_line(tangle, lang) for tangle in shown]
    if len(hidden_tangles) > len(shown):
        lines += ["", t("report.more", lang, count=len(hidden_tangles) - len(shown))]
    return lines


def _tangle_line(members: list[str], lang: Lang) -> str:
    """Render one tangle as its size and up to ``MAX_TANGLE_MEMBERS_SHOWN`` members.

    Args:
        members: Modules of the tangle, sorted.
        lang: Report language.

    Returns:
        One Markdown list item.
    """
    shown = ", ".join(f"`{m}`" for m in members[:MAX_TANGLE_MEMBERS_SHOWN])
    hidden = len(members) - MAX_TANGLE_MEMBERS_SHOWN
    more = f" {t('report.more', lang, count=hidden)}" if hidden > 0 else ""
    return f"- **{t('report.tangle_size', lang, size=len(members))}**: {shown}{more}"


def _packages(result: AnalysisResult, lang: Lang) -> list[str]:
    """Build the package overview, or nothing when there is no package structure to show.

    Args:
        result: The deterministic analysis.
        lang: Report language.

    Returns:
        Markdown lines of the section; empty with fewer than ``MIN_PACKAGES_SHOWN`` packages.
    """
    if len(result.packages) < MIN_PACKAGES_SHOWN:
        return []
    lines = [
        f"## {t('report.packages', lang)}",
        "",
        t("report.packages_intro", lang),
        "",
        f"| {t('report.package', lang)} | {t('report.package_modules', lang)} | Ca | Ce "
        f"| {t('report.instability', lang)} |",
        "|---|---:|---:|---:|---:|",
    ]
    for package in result.packages[:MAX_PACKAGES_IN_TABLE]:
        lines.append(
            f"| `{package.name}` | {package.modules} | {package.afferent} "
            f"| {package.efferent} | {package.instability:.2f} |"
        )
    if any(kind.is_native for kind in result.virtual.values()):
        lines += ["", t("report.packages_native_note", lang)]
    if len(result.packages) > MAX_PACKAGES_IN_TABLE:
        lines += [
            "",
            t(
                "report.packages_showing",
                lang,
                shown=MAX_PACKAGES_IN_TABLE,
                total=len(result.packages),
            ),
        ]
    if result.package_edges:
        lines += ["", f"### {t('report.package_edges', lang)}", ""]
        for edge in result.package_edges[:MAX_PACKAGE_EDGES_SHOWN]:
            key = _plural_key(edge.imports)
            label = t(f"report.package_edge.{key}", lang, imports=edge.imports)
            lines.append(f"- `{edge.source}` → `{edge.target}` ({label})")
        hidden = len(result.package_edges) - MAX_PACKAGE_EDGES_SHOWN
        if hidden > 0:
            lines.append(f"- {t('report.more', lang, count=hidden)}")
    return lines


def _coupled(result: AnalysisResult, lang: Lang) -> list[str]:
    """Build the table of the most coupled modules, capped at ``MAX_MODULES_IN_TABLE``.

    Args:
        result: The deterministic analysis.
        lang: Report language.

    Returns:
        Markdown lines of the section.
    """
    lines = [f"## {t('report.coupled', lang)}", ""]
    modules = result.high_coupling_modules
    if not modules:
        return [*lines, t("report.no_coupled", lang)]
    has_consumers = any(
        result.coupling_metrics[name].consumers for name in modules[:MAX_MODULES_IN_TABLE]
    )
    lines.append(t("report.coupled_intro", lang, top=TOP_COUPLED_SHARE))
    if has_consumers:
        lines += ["", t("report.coupled_consumers_note", lang)]
    consumers_header = f" | {t('report.consumers', lang)}" if has_consumers else ""
    lines += [
        "",
        f"| {t('report.module', lang)} | Ca | Ce | {t('report.instability', lang)} "
        f"| {t('report.impact', lang)}{consumers_header} |",
        "|---|---:|---:|---:|---:|" + ("---:|" if has_consumers else ""),
    ]
    for name in modules[:MAX_MODULES_IN_TABLE]:
        m = result.coupling_metrics[name]
        consumers = f" | {m.consumers}" if has_consumers else ""
        lines.append(
            f"| {_module_name(name, result, lang)} | {m.afferent} | {_efferent(name, result)} "
            f"| {_instability(name, result)} "
            f"| {result.impact.get(name, NOT_MEASURED)}{consumers} |"
        )
    if len(modules) > MAX_MODULES_IN_TABLE:
        showing = t(
            "report.showing",
            lang,
            shown=MAX_MODULES_IN_TABLE,
            total=len(modules),
            top=TOP_COUPLED_SHARE,
        )
        lines += ["", showing]
    return lines


def _shows_distributions(result: AnalysisResult) -> bool:
    """Tell whether the report shows the distributions of the project.

    Args:
        result: The deterministic analysis.

    Returns:
        True with at least ``MIN_DISTRIBUTIONS_SHOWN`` named distributions, or when one
        cannot be installed alone (with a single one, only unpackaged code blocks it).
    """
    return len(result.distributions) >= MIN_DISTRIBUTIONS_SHOWN or any(
        summary.installable is False for summary in result.distributions
    )


def _backticked(names: list[str] | tuple[str, ...]) -> str:
    """Return names in backticks, joined by commas.

    Args:
        names: Names to show.

    Returns:
        The joined names, or ``NOT_MEASURED`` when there are none.
    """
    return LIST_SEPARATOR.join(f"`{name}`" for name in names) or NOT_MEASURED


def _installable(summary: DistributionSummary, lang: Lang) -> str:
    """Render whether a distribution can be installed alone.

    Args:
        summary: The distribution's summary.
        lang: Report language.

    Returns:
        "yes", "no" with what blocks it, or "unknown".
    """
    if summary.installable is None:
        return t("report.installable.unknown", lang)
    if summary.installable:
        return t("report.installable.yes", lang)
    return t("report.installable.no", lang, blocker=summary.blocker)


def _distributions(result: AnalysisResult, lang: Lang) -> list[str]:
    """Build the distributions section: what each one uses and whether it installs alone.

    Args:
        result: The deterministic analysis.
        lang: Report language.

    Returns:
        Markdown lines of the section.
    """
    lines = [
        f"## {t('report.distributions', lang)}",
        "",
        t("report.distributions_intro", lang),
        "",
        f"| {t('report.distribution', lang)} | {t('report.package_modules', lang)} "
        f"| {t('report.distribution_uses', lang)} "
        f"| {t('report.distribution_installable', lang)} |",
        "|---|---:|---|---|",
    ]
    for summary in result.distributions:
        lines.append(
            f"| `{summary.name}` | {summary.modules} | {_backticked(summary.uses)} "
            f"| {_installable(summary, lang)} |"
        )
    return lines


def _scripts(result: AnalysisResult, lang: Lang) -> list[str]:
    """Build the scripts section: one line per directory with what its scripts use.

    Args:
        result: The deterministic analysis.
        lang: Report language.

    Returns:
        Markdown lines of the section.
    """
    lines = [f"## {t('report.scripts', lang)}", "", t("report.scripts_intro", lang), ""]
    for group in result.script_groups:
        key = _plural_key(group.scripts)
        uses = ", ".join(f"`{use}`" for use in group.uses) or NOT_MEASURED
        lines.append(
            t(
                f"report.script_group.{key}",
                lang,
                directory=group.directory,
                count=group.scripts,
                uses=uses,
            )
        )
    return lines


def _findings(result: AnalysisResult, lang: Lang) -> list[str]:
    """Build the findings section: each rule explained once, then its modules.

    Args:
        result: The deterministic analysis.
        lang: Report language.

    Returns:
        Markdown lines of the section.
    """
    lines = [f"## {t('report.findings', lang)}", ""]
    if not result.findings:
        return [*lines, t("report.no_findings", lang)]
    for kind in FindingKind:
        group = [finding for finding in result.findings if finding.kind is kind]
        if not group:
            continue
        lines += [
            f"### {t(f'finding.{kind}.title', lang)} ({len(group)})",
            "",
            t(f"finding.{kind}.explanation", lang),
            "",
            f"*{t('report.recommendation', lang)}:* {t(f'finding.{kind}.recommendation', lang)}",
            "",
        ]
        shown = len(group) if kind in UNCAPPED_FINDINGS else MAX_FINDINGS_PER_KIND
        lines += [_finding_line(finding, result, lang) for finding in group[:shown]]
        hidden = len(group) - shown
        if hidden > 0:
            lines.append(f"- {t('report.more', lang, count=hidden)}")
        lines.append("")
    return lines[:-1]


def _uses(evidence: Evidence, lang: Lang) -> str:
    """Render how many required, lazy and guarded imports a finding counts.

    Args:
        evidence: Evidence of the finding; a missing count is zero.
        lang: Report language.

    Returns:
        The counts as text.
    """
    return t(
        "finding.uses",
        lang,
        required=evidence.get("required", 0),
        lazy=evidence.get("lazy", 0),
        guarded=evidence.get("guarded", 0),
    )


def _fix_text(finding: Finding, lang: Lang) -> str:
    """Render the deterministic fix of a distribution finding.

    Args:
        finding: A finding of rules 6-9.
        lang: Report language.

    Returns:
        The fix, ready to copy.
    """
    evidence = finding.evidence
    extras = str(evidence.get("extras", ""))
    cuts = str(evidence.get("cuts", ""))
    values = {
        **evidence,
        "source": finding.modules[0],
        "target": finding.modules[-1],
        "extras": _backticked(extras.split(LIST_SEPARATOR)) if extras else NOT_MEASURED,
        "cuts": LIST_SEPARATOR.join(
            EDGE_ARROW.join(f"`{end}`" for end in cut.split(EDGE_ARROW))
            for cut in cuts.split(LIST_SEPARATOR)
        ),
    }
    return t(f"finding.fix.{evidence['fix']}", lang, **values)


def _distribution_finding_line(finding: Finding, result: AnalysisResult, lang: Lang) -> str:
    """Render a finding of rules 6-9: its edge or cycle, then its fix as sub-items.

    Args:
        finding: A finding of rules 6-9.
        result: The deterministic analysis, for the edges inside a cycle.
        lang: Report language.

    Returns:
        A multi-line Markdown list item.
    """
    fix = f"  - {t('finding.fix', lang)}: {_fix_text(finding, lang)}"
    if finding.kind in EDGE_FINDINGS:
        source, target = finding.modules
        details = [
            _uses(finding.evidence, lang),
            t("finding.first", lang, first=finding.evidence["first"]),
        ]
        if "groups" in finding.evidence:
            groups = _backticked(str(finding.evidence["groups"]).split(LIST_SEPARATOR))
            details.append(t("finding.only_in_groups", lang, groups=groups))
        return f"- `{source}` → `{target}` ({DETAIL_SEPARATOR.join(details)})\n{fix}"
    members = set(finding.modules)
    lines = [f"- {CYCLE_SEPARATOR.join(f'`{member}`' for member in finding.modules)}"]
    for edge in result.distribution_edges:
        if edge.source in members and edge.target in members:
            status = t(f"finding.status.{edge.status}", lang, extras=_backticked(edge.extras))
            if edge.groups:
                groups = t("finding.only_in_groups", lang, groups=_backticked(edge.groups))
                status = f"{status} ({groups})"
            uses = t(
                "finding.uses",
                lang,
                required=edge.counts.required,
                lazy=edge.counts.lazy,
                guarded=edge.counts.guarded,
            )
            lines.append(f"  - `{edge.source}` → `{edge.target}`: {status}; {uses}")
    return "\n".join([*lines, fix])


def _pairs(value: object) -> list[tuple[str, str]]:
    """Split ``symbol:value`` pairs of the evidence.

    Args:
        value: Evidence value such as ``"Model:app.models, helper:app.util"``.

    Returns:
        The pairs, in order.
    """
    pairs = []
    for item in str(value).split(LIST_SEPARATOR):
        symbol, _, rest = item.partition(PAIR_SEPARATOR)
        if symbol:
            pairs.append((symbol, rest))
    return pairs


def _import_from_text(evidence: Evidence, lang: Lang) -> str:
    """Render the ``import_from`` fix: each symbol with the module that defines it.

    Args:
        evidence: Evidence of a ``MISSING_MODULE`` finding with ``fix = import_from``.
        lang: Report language.

    Returns:
        The fix text, ending with the symbols no module defines, if any.
    """
    others = dict(_pairs(evidence["also_defined"]))
    items = []
    for symbol, module in _pairs(evidence["defined_in"]):
        count = int(others.get(symbol, 0))
        extra = t("finding.also_defined", lang, count=count) if count else ""
        items.append(
            t("finding.fix.import_from.item", lang, symbol=symbol, module=module, others=extra)
        )
    text = t("finding.fix.import_from", lang, items=DETAIL_SEPARATOR.join(items))
    undefined = str(evidence.get("undefined", ""))
    if undefined:
        symbols = _backticked(undefined.split(LIST_SEPARATOR))
        text += DETAIL_SEPARATOR + t("finding.fix.undefined", lang, symbols=symbols)
    return text


def _missing_module_line(finding: Finding, result: AnalysisResult, lang: Lang) -> str:
    """Render a finding of rule 10: the missing module, its uses, then its fix.

    Args:
        finding: A ``MISSING_MODULE`` finding.
        result: The deterministic analysis, to mark a namespace package as the closest.
        lang: Report language.

    Returns:
        A multi-line Markdown list item.
    """
    evidence = finding.evidence
    (module,) = finding.modules
    first = t("finding.first", lang, first=evidence["first"])
    symbols = str(evidence["symbols"])
    names = _backticked(symbols.split(LIST_SEPARATOR)) if symbols else ""
    if evidence["fix"] == FIX_IMPORT_FROM:
        text = _import_from_text(evidence, lang)
    elif names:
        text = t("finding.fix.restore_or_remove", lang, module=module, symbols=names)
    else:
        closest = _module_name(str(evidence["closest"]), result, lang)
        text = t("finding.fix.restore_or_remove.module", lang, module=module, closest=closest)
    fix = f"  - {t('finding.fix', lang)}: {text}"
    return f"- `{module}` ({_uses(evidence, lang)}{DETAIL_SEPARATOR}{first})\n{fix}"


def _native_works(native: NativeModule, lang: Lang) -> str:
    """Render whether packaged code runs without a native module.

    Args:
        native: One row of the native boundary.
        lang: Report language.

    Returns:
        "yes", or "no" with the number of unguarded uses and the first one.
    """
    if native.works_without:
        return t("report.native_works.yes", lang)
    key = _plural_key(len(native.unguarded))
    return t(
        f"report.native_works.no.{key}",
        lang,
        count=len(native.unguarded),
        first=native.unguarded[0],
    )


def _native_boundary(result: AnalysisResult, lang: Lang) -> list[str]:
    """Build the native boundary: each compiled or stub-only module and how it is used.

    Args:
        result: The deterministic analysis.
        lang: Report language.

    Returns:
        Markdown lines of the section.
    """
    lines = [
        f"## {t('report.native', lang)}",
        "",
        t("report.native_intro", lang),
        "",
        f"| {t('report.module', lang)} | {t('report.native_kind', lang)} "
        f"| {t('report.native_evidence', lang)} | Ca | {t('report.native_uses', lang)} "
        f"| {t('report.native_works', lang)} | {t('report.native_out', lang)} |",
        "|---|---|---|---:|---|---|---|",
    ]
    for native in result.native[:MAX_NATIVE_IN_TABLE]:
        uses = f"{native.required} / {native.lazy} / {native.guarded} / {native.type_only}"
        lines.append(
            f"| `{native.name}` | {t(f'report.native_kind.{native.kind}', lang)} "
            f"| {_backticked(native.evidence)} | {native.afferent} | {uses} "
            f"| {_native_works(native, lang)} | {t(f'report.native_out.{native.kind}', lang)} |"
        )
    hidden = len(result.native) - MAX_NATIVE_IN_TABLE
    if hidden > 0:
        lines += ["", t("report.more", lang, count=hidden)]
    return [*lines, "", t("report.native_note", lang)]


def _native_finding_line(finding: Finding, result: AnalysisResult, lang: Lang) -> str:
    """Render a finding of rule 11: its uses, the unguarded locations, then the fix.

    Args:
        finding: An ``OPTIONAL_NATIVE_REQUIRED`` finding.
        result: The deterministic analysis, to mark the module with its kind.
        lang: Report language.

    Returns:
        A multi-line Markdown list item.
    """
    evidence = finding.evidence
    (module,) = finding.modules
    guarded = t("finding.native_guarded", lang, first=evidence["first_guarded"])
    shown = str(evidence["unguarded"]).split(LIST_SEPARATOR)
    locations = _backticked(shown)
    hidden = int(evidence["unguarded_total"]) - len(shown)
    if hidden > 0:
        locations += f" ({t('report.more', lang, count=hidden)})"
    fix = t(
        "finding.fix.guard_or_drop_fallback",
        lang,
        first_guarded=evidence["first_guarded"],
        module=module,
    )
    return (
        f"- {_module_name(module, result, lang)} ({_uses(evidence, lang)}{DETAIL_SEPARATOR}"
        f"{guarded})\n  - {t('finding.native_unguarded', lang)}: {locations}\n"
        f"  - {t('finding.fix', lang)}: {fix}"
    )


def _wildcard_fix_line(fix: WildcardFix, module: str, lang: Lang) -> str:
    """Render the fix of one star import statement, with its notes.

    Args:
        fix: The fix.
        module: The star-imported module.
        lang: Report language.

    Returns:
        One Markdown sub-item.
    """
    if fix.action is WildcardAction.NO_FIX:
        text = t(
            f"finding.wildcard.reason.{fix.reason}",
            lang,
            module=module,
            importer=fix.importer,
            names=_backticked(fix.reason_names),
        )
    elif fix.action is WildcardAction.REMOVE:
        text = t("finding.wildcard.fix.remove", lang, module=module)
    elif fix.action is WildcardAction.REMOVE_SELF:
        text = t("finding.wildcard.fix.remove_self", lang)
    else:
        text = f"`from {module} import {LIST_SEPARATOR.join(fix.names)}`"
        needers: dict[str, list[str]] = {}
        for needer, name in fix.kept_for:
            needers.setdefault(needer, []).append(name)
        notes = [
            t("finding.wildcard.note.kept", lang, importer=needer, names=_backticked(names))
            for needer, names in needers.items()
            if needer != ANY_READER
        ]
        if ANY_READER in needers:
            notes.insert(0, t("finding.wildcard.note.any_reader", lang, module=fix.importer))
        origins: dict[str, list[str]] = {}
        for origin, name in fix.defined_elsewhere:
            origins.setdefault(origin, []).append(name)
        notes += [
            t("finding.wildcard.note.elsewhere", lang, origin=origin, names=_backticked(names))
            for origin, names in origins.items()
        ]
        if fix.external:
            notes.append(t("finding.wildcard.note.external", lang, names=_backticked(fix.external)))
        if notes:
            text += f" ({DETAIL_SEPARATOR.join(notes)})"
    return f"  - `{fix.location}`: {text}"


def _wildcard_line(finding: Finding, result: AnalysisResult, lang: Lang) -> str:
    """Render a finding of rule 12: the summary, then the fix of each statement.

    Args:
        finding: A ``WILDCARD_IMPORT`` finding.
        result: The deterministic analysis, with the fixes.
        lang: Report language.

    Returns:
        A multi-line Markdown list item.
    """
    (module,) = finding.modules
    is_self = finding.evidence["kind"] == KIND_SELF
    wildcard = next(w for w in result.wildcards if (w.name, w.is_self) == (module, is_self))
    statements = len(wildcard.fixes)
    if wildcard.is_self:
        summary = t("finding.wildcard.self", lang, count=statements)
    else:
        parts = [
            t(
                f"finding.wildcard.importers.{_plural_key(wildcard.importers)}",
                lang,
                count=wildcard.importers,
            ),
            t(f"finding.wildcard.statements.{_plural_key(statements)}", lang, count=statements),
        ]
        summary = (
            PART_SEPARATOR.join(parts)
            + DETAIL_SEPARATOR
            + t(
                f"finding.wildcard.used.{_plural_key(statements)}.{_plural_key(wildcard.names)}",
                lang,
                used_min=wildcard.used_min,
                used_max=wildcard.used_max,
                names=wildcard.names,
            )
        )
        if wildcard.unused:
            summary += DETAIL_SEPARATOR + t(
                f"finding.wildcard.unused.{_plural_key(wildcard.unused)}",
                lang,
                count=wildcard.unused,
            )
        if wildcard.no_fix:
            summary += DETAIL_SEPARATOR + t(
                f"finding.wildcard.no_fix.{_plural_key(wildcard.no_fix)}",
                lang,
                count=wildcard.no_fix,
            )
        if wildcard.reexported:
            summary += DETAIL_SEPARATOR + t(
                f"finding.wildcard.reexported.{_plural_key(wildcard.reexported)}",
                lang,
                count=wildcard.reexported,
            )
    lines = [f"- `{module}` ({summary})"]
    # Every statement and every name: the fix is meant to be copied.
    lines += [_wildcard_fix_line(fix, module, lang) for fix in wildcard.fixes]
    return "\n".join(lines)


def _finding_line(finding: Finding, result: AnalysisResult, lang: Lang) -> str:
    """Render one finding as a list item with the numbers behind it.

    Args:
        finding: The finding to render.
        result: The deterministic analysis; a bottleneck shows its measured impact, a
            cycle between distributions its edges.
        lang: Report language.

    Returns:
        One Markdown list item; with sub-items for the findings of rules 6-9.
    """
    evidence = finding.evidence
    impact = result.impact
    if finding.kind in (*EDGE_FINDINGS, FindingKind.DISTRIBUTION_CYCLE):
        return _distribution_finding_line(finding, result, lang)
    if finding.kind is FindingKind.MISSING_MODULE:
        return _missing_module_line(finding, result, lang)
    if finding.kind is FindingKind.OPTIONAL_NATIVE_REQUIRED:
        return _native_finding_line(finding, result, lang)
    if finding.kind is FindingKind.WILDCARD_IMPORT:
        return _wildcard_line(finding, result, lang)
    if finding.kind is FindingKind.UNSTABLE_DEPENDENCY:
        source, target = finding.modules
        return (
            f"- `{source}` → `{target}` (Ca {evidence['afferent_from']}, "
            f"I {evidence['instability_from']:.2f} → {evidence['instability_to']:.2f})"
        )
    if finding.kind is FindingKind.LAYER_VIOLATION:
        source, target = finding.modules
        layers = t(
            "finding.layers",
            lang,
            layer_from=evidence["layer_from"],
            layer_to=evidence["layer_to"],
        )
        return f"- `{source}` → {_module_name(target, result, lang)} ({layers})"
    (module,) = finding.modules
    if finding.kind is FindingKind.ORPHAN:
        return f"- `{module}`"
    numbers = f"Ca {evidence['afferent']}, Ce {evidence['efferent']}"
    if finding.kind is FindingKind.BOTTLENECK and module in impact:
        numbers += f", {t('finding.impact', lang, impact=impact[module])}"
    return f"- `{module}` ({numbers})"


def _ai(context: ReportContext, lang: Lang) -> list[str]:
    """Build the AI problems section, or the notice explaining its absence.

    Args:
        context: Report context.
        lang: Report language.

    Returns:
        Markdown lines of the section.
    """
    lines = [f"## {t('report.ai', lang)}", ""]
    if context.ai_report is None:
        if context.ai_status is AIStatus.FAILED:
            failure = context.ai_failure or AIFailure.CALL_ERROR
            notice = t(
                f"report.ai.failed.{failure}",
                lang,
                error_type=context.ai_error_type or "",
            )
        else:
            notice = t(f"report.ai.{context.ai_status}", lang)
        return [*lines, notice]
    if context.ai_dropped_problems:
        lines += [t("report.ai.dropped", lang, count=context.ai_dropped_problems), ""]
    problems = filter_by_severity(context.ai_report.problems, context.min_severity)
    if not problems:
        return [*lines, t("report.ai.no_problems", lang)]
    for problem in problems:
        modules = ", ".join(f"`{m}`" for m in problem.affected_modules)
        lines += [
            f"- **[{problem.severity}] {problem.title}** — {modules}",
            f"  {problem.description}",
            f"  *{t('report.recommendation', lang)}:* {problem.recommendation}",
        ]
    return lines


def _location(warning: ParseWarning, root: Path) -> str:
    """Return ``path:line`` relative to the project root, or empty for project-level warnings.

    Args:
        warning: The warning to locate.
        root: Project root.

    Returns:
        The location as Markdown code, followed by a separator, or an empty string.
    """
    if warning.path is None:
        return ""
    path = warning.path
    if path.is_relative_to(root):
        path = path.relative_to(root)
    location = path.as_posix() + (f":{warning.line}" if warning.line else "")
    return f"`{location}` — "


def _warnings(warnings: list[ParseWarning], root: Path, lang: Lang) -> list[str]:
    """Group warnings by kind, showing a few examples of each.

    Grouping keeps huge projects readable: 264 star imports read as one
    heading with ``MAX_WARNING_EXAMPLES`` examples, not 264 lines.

    Args:
        warnings: Warnings collected during the analysis.
        root: Project root, to show paths relative to it.
        lang: Report language.

    Returns:
        Markdown lines of the section.
    """
    groups: dict[WarningCode, list[ParseWarning]] = defaultdict(list)
    for warning in warnings:
        groups[warning.code].append(warning)
    lines = [f"## {t('report.warnings', lang)}"]
    for code, group in groups.items():
        lines += ["", f"### {t(f'warning_title.{code}', lang)} ({len(group)})", ""]
        for warning in group[:MAX_WARNING_EXAMPLES]:
            lines.append(f"- {_location(warning, root)}{translate_warning(warning, lang)}")
        hidden = len(group) - MAX_WARNING_EXAMPLES
        if hidden > 0:
            lines.append(f"- {t('report.more', lang, count=hidden)}")
    return lines
