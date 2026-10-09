import json
import re
from dataclasses import replace
from pathlib import Path

import networkx as nx
import pathspec
import pytest

from unskein.ai.models import (
    AIContext,
    AIReport,
    CycleSummary,
    ModuleCoupling,
    PackageEdgeSummary,
    Problem,
    TangleSummary,
)
from unskein.ai.prompts import (
    MAX_CYCLE_MEMBERS_IN_PROMPT,
    MAX_CYCLES_IN_PROMPT,
    MAX_FINDINGS_PER_KIND_IN_PROMPT,
    MAX_MODULES_IN_PROMPT,
    MAX_PACKAGE_EDGES_IN_PROMPT,
    MAX_PROMPT_CHARS,
    MAX_TANGLE_MEMBERS_IN_PROMPT,
    MAX_TANGLES_IN_PROMPT,
    SYSTEM_PROMPT,
    UNSTABLE_THRESHOLD,
    build_context,
    build_messages,
    ground_report,
    shrink_context,
)
from unskein.graph.findings import Finding, FindingKind
from unskein.graph.metrics import AnalysisResult, analyze, compute_coupling
from unskein.graph.packages import PackageEdge
from unskein.i18n import Lang
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.python_parser import PythonAdapter


def analyze_fixture(root: Path) -> AnalysisResult:
    """Discover, parse, resolve and analyze a fixture project.

    Args:
        root: Fixture project directory.

    Returns:
        The analysis of the fixture.
    """
    adapter = PythonAdapter()
    files = sorted(adapter.discover_files(root, pathspec.PathSpec([])))
    return analyze(resolve_indirection(adapter.parse(files, root)))


def synthetic_result(module_count: int, cycle_count: int, tangle_count: int) -> AnalysisResult:
    """Build an analysis with many long-named modules, cycles and tangles.

    Args:
        module_count: Number of modules (a dependency chain).
        cycle_count: Number of two-to-eight-module cycles.
        tangle_count: Number of tangles with 30 members each.

    Returns:
        The synthetic analysis.
    """
    names = [f"company.platform.service_{i:04d}.handlers" for i in range(module_count)]
    graph = nx.DiGraph()
    graph.add_nodes_from(names)
    graph.add_edges_from(zip(names, names[1:], strict=False))
    cycles = [names[i : i + 2 + i % 7] for i in range(cycle_count)]
    tangles = [names[i * 30 : i * 30 + 30] for i in range(tangle_count)]
    return AnalysisResult(
        graph=graph,
        coupling_metrics=compute_coupling(graph),
        cycles=cycles,
        high_coupling_modules=[],
        cycles_truncated=True,
        tangles=tangles,
    )


def tangle_result(tangle_size: int, tangle_count: int, module_count: int) -> AnalysisResult:
    """Build an analysis like ``find_cycles`` gives inside big tangles.

    Args:
        tangle_size: Modules per tangle.
        tangle_count: Number of tangles.
        module_count: Total modules, at least ``tangle_size * tangle_count``.

    Returns:
        An analysis with 100 cycles, the shortest already nearly tangle-sized.
    """
    names = [f"company.platform.subsystem_{i:04d}.internal.handlers" for i in range(module_count)]
    graph = nx.DiGraph()
    graph.add_nodes_from(names)
    graph.add_edges_from(zip(names, names[1:], strict=False))
    cycles = [names[: tangle_size - 99 + i] for i in range(100)]
    tangles = [names[i * tangle_size : (i + 1) * tangle_size] for i in range(tangle_count)]
    return AnalysisResult(
        graph=graph,
        coupling_metrics=compute_coupling(graph),
        cycles=cycles,
        high_coupling_modules=[],
        cycles_truncated=True,
        tangles=tangles,
    )


def test_context_summarizes_a_small_project(circular_imports: Path) -> None:
    context = build_context(analyze_fixture(circular_imports))
    assert context.total_modules == 3
    assert context.total_cycles == 1
    assert [(c.length, c.members) for c in context.cycles] == [(2, ["app.a", "app.b"])]
    assert [t.size for t in context.tangles] == [2]
    assert context.warning_counts == {}


def test_project_without_cycles_tangles_or_warnings_gives_a_valid_context(
    simple_project: Path,
) -> None:
    context = build_context(analyze_fixture(simple_project))
    assert (context.cycles, context.tangles, context.warning_counts) == ([], [], {})
    assert context.total_tangles == 0


def test_lists_are_truncated_but_totals_are_kept() -> None:
    context = build_context(synthetic_result(module_count=400, cycle_count=60, tangle_count=8))
    assert len(context.cycles) == MAX_CYCLES_IN_PROMPT
    assert context.total_cycles == 60
    assert context.cycles_truncated is True
    assert len(context.tangles) == MAX_TANGLES_IN_PROMPT
    assert context.total_tangles == 8
    assert all(len(c.members) <= MAX_CYCLE_MEMBERS_IN_PROMPT for c in context.cycles)
    assert all(len(t.members) <= MAX_TANGLE_MEMBERS_IN_PROMPT for t in context.tangles)
    assert context.tangles[0].size == 30
    assert len(context.top_coupled_modules) == MAX_MODULES_IN_PROMPT


def test_context_carries_hidden_tangles_truncated_with_their_total() -> None:
    result = synthetic_result(module_count=400, cycle_count=0, tangle_count=0)
    hidden = [[f"h{group}.m{index}" for index in range(30)] for group in range(8)]
    context = build_context(replace(result, hidden_tangles=hidden))
    assert context.total_hidden_tangles == 8
    assert len(context.hidden_tangles) == MAX_TANGLES_IN_PROMPT
    assert context.hidden_tangles[0].size == 30
    assert context.hidden_tangles[0].members == hidden[0][:MAX_TANGLE_MEMBERS_IN_PROMPT]


def test_system_prompt_rates_hidden_tangles_as_medium() -> None:
    assert "hidden_tangles" in SYSTEM_PROMPT
    medium = SYSTEM_PROMPT.split("- medium:")[1].split("- low:")[0]
    assert "hidden tangle" in medium


def test_cycles_come_shortest_first() -> None:
    context = build_context(synthetic_result(module_count=100, cycle_count=40, tangle_count=0))
    lengths = [cycle.length for cycle in context.cycles]
    assert lengths == sorted(lengths)


def test_top_coupled_modules_are_ranked_by_ca_plus_ce_then_name() -> None:
    graph = nx.DiGraph()
    graph.add_edges_from([("z", "hub"), ("a", "hub"), ("hub", "leaf")])
    result = AnalysisResult(
        graph=graph,
        coupling_metrics=compute_coupling(graph),
        cycles=[],
        high_coupling_modules=[],
    )
    top = build_context(result).top_coupled_modules
    assert [m.module for m in top] == ["hub", "a", "leaf", "z"]
    assert (top[0].ca, top[0].ce, top[0].instability) == (2, 1, 0.33)


def user_blocks(messages: list[dict[str, str]]) -> list[str]:
    """Return the fenced JSON blocks of the user message.

    Args:
        messages: Messages built by ``build_messages``.

    Returns:
        The text of each ```json block, in order.
    """
    return re.findall(r"```json\n(.*?)\n```", messages[1]["content"], re.DOTALL)


def small_context(circular_imports: Path) -> AIContext:
    """Build the context of the circular-imports fixture.

    Args:
        circular_imports: Fixture project directory.

    Returns:
        Its AI context.
    """
    return build_context(analyze_fixture(circular_imports))


def test_messages_are_system_then_user(circular_imports: Path) -> None:
    messages = build_messages(small_context(circular_imports), Lang.EN)
    assert [m["role"] for m in messages] == ["system", "user"]
    assert SYSTEM_PROMPT in messages[0]["content"]


def test_language_instruction_targets_the_free_text_fields(circular_imports: Path) -> None:
    context = small_context(circular_imports)
    assert "Spanish" in build_messages(context, Lang.ES)[0]["content"]
    assert "English" in build_messages(context, Lang.EN)[0]["content"]


def test_rubric_never_flags_a_stable_module_as_a_problem() -> None:
    assert "near 0" not in SYSTEM_PROMPT
    assert "Never flag a module only for low instability" in SYSTEM_PROMPT


def test_rubric_flags_volatile_modules_others_depend_on() -> None:
    assert f"instability >= {UNSTABLE_THRESHOLD}" in SYSTEM_PROMPT
    assert "ca > 0" in SYSTEM_PROMPT


def test_system_prompt_states_the_severity_rubric_and_literal_names() -> None:
    assert "high" in SYSTEM_PROMPT and "tangle" in SYSTEM_PROMPT
    assert "exactly as given" in SYSTEM_PROMPT
    assert "Do not invent" in SYSTEM_PROMPT


def test_user_message_holds_the_data_then_the_schema(circular_imports: Path) -> None:
    data, schema = user_blocks(build_messages(small_context(circular_imports), Lang.EN))
    assert json.loads(data)["cycles"] == [{"length": 2, "members": ["app.a", "app.b"]}]
    assert json.loads(schema) == AIReport.model_json_schema()


def test_class_docstrings_stay_out_of_the_json_schema() -> None:
    schema = AIReport.model_json_schema()
    assert "description" not in schema
    assert all("description" not in definition for definition in schema["$defs"].values())


def test_the_prompt_schema_block_has_no_class_description(circular_imports: Path) -> None:
    _, schema = user_blocks(build_messages(small_context(circular_imports), Lang.EN))
    assert "v0.1" not in schema
    assert "Validated LLM" not in schema


def test_the_same_project_gives_the_same_prompt(circular_imports: Path) -> None:
    context = small_context(circular_imports)
    assert build_messages(context, Lang.EN) == build_messages(context, Lang.EN)


def test_unicode_and_brace_module_names_stay_literal_and_valid() -> None:
    graph = nx.DiGraph()
    graph.add_edge("pkg.módulo_ñ", "pkg.{weird}")
    result = AnalysisResult(
        graph=graph, coupling_metrics=compute_coupling(graph), cycles=[], high_coupling_modules=[]
    )
    data, _ = user_blocks(build_messages(build_context(result), Lang.EN))
    names = {m["module"] for m in json.loads(data)["top_coupled_modules"]}
    assert names == {"pkg.módulo_ñ", "pkg.{weird}"}
    assert "\\u" not in data


def test_a_large_project_stays_under_the_prompt_size_limit() -> None:
    context = build_context(synthetic_result(module_count=2000, cycle_count=90, tangle_count=9))
    messages = build_messages(context, Lang.EN)
    assert len(messages[1]["content"]) <= MAX_PROMPT_CHARS


def test_a_long_cycle_reports_its_real_length_with_capped_members() -> None:
    context = build_context(tangle_result(tangle_size=120, tangle_count=1, module_count=200))
    shortest = context.cycles[0]
    assert shortest.length == 21
    assert len(shortest.members) == MAX_CYCLE_MEMBERS_IN_PROMPT


def test_the_worst_case_tangle_stays_under_the_prompt_size_limit() -> None:
    context = build_context(tangle_result(tangle_size=120, tangle_count=6, module_count=2000))
    messages = build_messages(context, Lang.EN)
    assert len(messages[1]["content"]) <= MAX_PROMPT_CHARS


def long_named_context(name_length: int, count: int) -> AIContext:
    """Build a context whose lists are full of very long module names.

    Args:
        name_length: Length of every module name.
        count: Items per list and members per tangle or cycle.

    Returns:
        The context, far above the prompt size limit for long names.
    """
    names = [f"m{index}".ljust(name_length, "x") for index in range(count)]
    return AIContext(
        total_modules=count,
        total_dependencies=count,
        tangles=[TangleSummary(size=count, members=names) for _ in range(count)],
        total_tangles=count,
        hidden_tangles=[TangleSummary(size=count, members=names) for _ in range(count)],
        total_hidden_tangles=count,
        cycles=[CycleSummary(length=count, members=names) for _ in range(count)],
        total_cycles=count,
        cycles_truncated=False,
        top_coupled_modules=[
            ModuleCoupling(module=name, ca=1, ce=1, instability=0.5) for name in names
        ],
        warning_counts={},
    )


def test_an_oversized_context_is_shrunk_to_fit_the_prompt() -> None:
    messages = build_messages(long_named_context(name_length=120, count=20), Lang.EN)
    assert len(messages[1]["content"]) <= MAX_PROMPT_CHARS


def test_shrinking_keeps_totals_and_the_first_items() -> None:
    context = long_named_context(name_length=120, count=20)
    data, _ = user_blocks(build_messages(context, Lang.EN))
    sent = json.loads(data)
    assert sent["total_tangles"] == 20 and sent["total_cycles"] == 20
    assert 1 <= len(sent["top_coupled_modules"]) < 20
    assert sent["top_coupled_modules"][0]["module"] == context.top_coupled_modules[0].module
    assert sent["tangles"][0]["size"] == 20


def test_shrink_halves_lists_and_members_but_keeps_at_least_one() -> None:
    shrunk = shrink_context(long_named_context(name_length=5, count=5))
    assert len(shrunk.top_coupled_modules) == 2
    assert len(shrunk.tangles) == 2 and len(shrunk.tangles[0].members) == 2
    assert len(shrunk.cycles) == 2 and len(shrunk.cycles[0].members) == 2
    assert len(shrunk.hidden_tangles) == 2 and len(shrunk.hidden_tangles[0].members) == 2
    assert shrunk.total_hidden_tangles == 5
    single = shrink_context(long_named_context(name_length=5, count=1))
    assert single == long_named_context(name_length=5, count=1)


def test_an_unfittable_context_is_still_sent_at_its_smallest() -> None:
    messages = build_messages(long_named_context(name_length=MAX_PROMPT_CHARS, count=3), Lang.EN)
    data, _ = user_blocks(messages)
    assert len(json.loads(data)["top_coupled_modules"]) == 1


def problem(modules: list[str], snippet: str | None = None) -> Problem:
    """Build a problem affecting some modules.

    Args:
        modules: Affected modules.
        snippet: Optional code snippet.

    Returns:
        The problem.
    """
    return Problem(
        severity="high",
        title=f"about {','.join(modules)}",
        description="d",
        affected_modules=modules,
        recommendation="r",
        code_snippet=snippet,
    )


def report_with(*problems: Problem) -> AIReport:
    """Build a report holding the given problems.

    Args:
        *problems: Problems of the report.

    Returns:
        The report.
    """
    return AIReport(summary="s", architecture_health="concerning", problems=list(problems))


def test_unknown_modules_are_removed_from_a_problem() -> None:
    graph = nx.DiGraph([("a", "b")])
    grounded = ground_report(report_with(problem(["a", "ghost", "b"])), graph).report
    assert grounded.problems[0].affected_modules == ["a", "b"]


def test_a_problem_naming_no_known_module_is_dropped() -> None:
    graph = nx.DiGraph([("a", "b")])
    grounded = ground_report(report_with(problem(["ghost"]), problem(["a"])), graph).report
    assert [p.affected_modules for p in grounded.problems] == [["a"]]


def test_code_snippets_are_cleared_until_suggestions_exist() -> None:
    graph = nx.DiGraph([("a", "b")])
    grounded = ground_report(report_with(problem(["a"], snippet="print('x')")), graph).report
    assert grounded.problems[0].code_snippet is None


def test_grounding_does_not_mutate_the_input() -> None:
    graph = nx.DiGraph([("a", "b")])
    original = report_with(problem(["a", "ghost"], snippet="x"))
    ground_report(original, graph)
    assert original.problems[0].affected_modules == ["a", "ghost"]
    assert original.problems[0].code_snippet == "x"


def test_dropped_problems_are_counted() -> None:
    graph = nx.DiGraph([("a", "b")])
    grounding = ground_report(
        report_with(problem(["ghost"]), problem(["a"]), problem(["x"])), graph
    )
    assert grounding.dropped_problems == 2


def test_nothing_dropped_counts_zero() -> None:
    graph = nx.DiGraph([("a", "b")])
    assert ground_report(report_with(problem(["a"])), graph).dropped_problems == 0


@pytest.mark.parametrize(
    "written",
    [
        "`app.core`",
        " app.core ",
        "app.core.",
        "'app.core'",
        '"app.core"',
        "app/core.py",
        "app/core/__init__.py",
        "src/app/core.py",
        "app\\core.py",
        "`app.core`.",
        "./app/core.py",
        "app.core.py",
    ],
)
def test_loosely_written_module_names_are_matched_to_the_graph(written: str) -> None:
    graph = nx.DiGraph([("app.core", "app.util")])
    grounding = ground_report(report_with(problem([written])), graph)
    assert grounding.report.problems[0].affected_modules == ["app.core"]
    assert grounding.dropped_problems == 0


def test_a_src_root_is_stripped_down_to_a_top_level_module() -> None:
    graph = nx.DiGraph([("main", "util")])
    grounding = ground_report(report_with(problem(["src/main.py"])), graph)
    assert grounding.report.problems[0].affected_modules == ["main"]


def test_other_leading_segments_are_never_guessed_away() -> None:
    graph = nx.DiGraph([("core", "util")])
    grounding = ground_report(report_with(problem(["app/core.py"])), graph)
    assert grounding.dropped_problems == 1
    assert grounding.report.problems == []


def test_a_real_src_package_is_matched_before_stripping_the_root() -> None:
    graph = nx.DiGraph([("src.app.core", "src.app.util")])
    grounding = ground_report(report_with(problem(["src/app/core.py"])), graph)
    assert grounding.report.problems[0].affected_modules == ["src.app.core"]


@pytest.mark.parametrize("written", ["", ".", "`", "src", "src/__init__.py", "__init__.py"])
def test_empty_or_bare_names_match_nothing(written: str) -> None:
    graph = nx.DiGraph([("app.core", "app.util")])
    assert ground_report(report_with(problem([written])), graph).dropped_problems == 1


def test_normalized_duplicates_are_listed_once() -> None:
    graph = nx.DiGraph([("a", "b")])
    grounding = ground_report(report_with(problem(["a", "`a`", "a."])), graph)
    assert grounding.report.problems[0].affected_modules == ["a"]


def with_findings(result: AnalysisResult, *findings: Finding) -> AnalysisResult:
    """Return a copy of an analysis that carries the given findings.

    Args:
        result: Analysis to copy.
        *findings: Findings to attach.

    Returns:
        The analysis with those findings.
    """
    return replace(result, findings=list(findings))


def test_context_carries_findings_capped_per_kind_with_real_totals() -> None:
    orphans = [
        Finding(FindingKind.ORPHAN, (f"m{i:02d}",), {})
        for i in range(MAX_FINDINGS_PER_KIND_IN_PROMPT + 4)
    ]
    bottleneck = Finding(
        FindingKind.BOTTLENECK, ("core.settings",), {"afferent": 25, "efferent": 9}
    )
    result = with_findings(synthetic_result(3, 0, 0), bottleneck, *orphans)

    context = build_context(result)

    assert context.finding_counts == {"bottleneck": 1, "orphan": len(orphans)}
    assert [f.kind for f in context.findings].count("orphan") == MAX_FINDINGS_PER_KIND_IN_PROMPT
    assert context.findings[0].modules == ["core.settings"]
    assert context.findings[0].evidence == {"afferent": 25, "efferent": 9}


def test_context_without_findings_has_empty_findings() -> None:
    context = build_context(synthetic_result(3, 0, 0))

    assert (context.findings, context.finding_counts) == ([], {})


def test_disabled_findings_add_nothing_to_the_context() -> None:
    result = replace(
        with_findings(synthetic_result(3, 0, 0), Finding(FindingKind.ORPHAN, ("a",), {})),
        findings_enabled=False,
    )

    assert build_context(result).findings == []


def test_shrinking_halves_the_findings_but_keeps_their_totals() -> None:
    orphans = [
        Finding(FindingKind.ORPHAN, (f"m{i:02d}",), {})
        for i in range(MAX_FINDINGS_PER_KIND_IN_PROMPT)
    ]
    context = build_context(with_findings(synthetic_result(3, 0, 0), *orphans))

    shrunk = shrink_context(context)

    assert 1 <= len(shrunk.findings) < len(context.findings)
    assert shrunk.finding_counts == context.finding_counts


def test_prompt_with_many_findings_still_fits_the_limit() -> None:
    findings = [
        Finding(kind, (f"pkg.very.long.module.name.number{i:03d}",), {"afferent": i, "efferent": i})
        for kind in FindingKind
        for i in range(200)
    ]
    context = build_context(with_findings(synthetic_result(500, 0, 0), *findings))

    messages = build_messages(context, Lang.EN)

    assert len(messages[1]["content"]) <= MAX_PROMPT_CHARS


def test_system_prompt_declares_findings_as_computed_facts() -> None:
    assert "Findings are architecture problems that fixed rules already computed" in SYSTEM_PROMPT
    assert "do not recompute or contradict them" in SYSTEM_PROMPT


def test_context_carries_the_largest_package_dependencies_with_the_real_total() -> None:
    edges = [
        PackageEdge(f"p{i:02d}", "core", 100 - i) for i in range(MAX_PACKAGE_EDGES_IN_PROMPT + 5)
    ]
    result = replace(synthetic_result(3, 0, 0), package_edges=edges)

    context = build_context(result)

    assert len(context.package_edges) == MAX_PACKAGE_EDGES_IN_PROMPT
    assert context.total_package_edges == len(edges)
    assert context.package_edges[0] == PackageEdgeSummary("p00", "core", 100)


def test_context_without_packages_has_empty_package_fields() -> None:
    context = build_context(synthetic_result(3, 0, 0))

    assert (context.package_edges, context.total_package_edges) == ([], 0)


def test_bottleneck_evidence_carries_its_measured_impact() -> None:
    bottleneck = Finding(
        FindingKind.BOTTLENECK, ("core.settings",), {"afferent": 25, "efferent": 9}
    )
    result = replace(
        with_findings(synthetic_result(3, 0, 0), bottleneck), impact={"core.settings": 54}
    )

    summary = build_context(result).findings[0]

    assert summary.evidence == {"afferent": 25, "efferent": 9, "impact": 54}


def test_other_findings_and_unmeasured_bottlenecks_get_no_impact() -> None:
    orphan = Finding(FindingKind.ORPHAN, ("lonely",), {})
    bottleneck = Finding(FindingKind.BOTTLENECK, ("hub",), {"afferent": 6, "efferent": 6})
    result = replace(
        with_findings(synthetic_result(3, 0, 0), orphan, bottleneck), impact={"lonely": 9}
    )

    evidence = {f.modules[0]: f.evidence for f in build_context(result).findings}

    assert "impact" not in evidence["lonely"]
    assert "impact" not in evidence["hub"]


def test_shrinking_halves_the_package_dependencies_but_keeps_their_total() -> None:
    edges = [PackageEdge(f"p{i}", "core", 10 - i) for i in range(MAX_PACKAGE_EDGES_IN_PROMPT)]
    context = build_context(replace(synthetic_result(3, 0, 0), package_edges=edges))

    shrunk = shrink_context(context)

    assert len(shrunk.package_edges) == MAX_PACKAGE_EDGES_IN_PROMPT // 2
    assert shrunk.total_package_edges == context.total_package_edges


def test_prompt_with_many_packages_still_fits_the_limit() -> None:
    edges = [PackageEdge(f"very.long.package.name.number{i:03d}", "core", 1) for i in range(500)]
    context = build_context(replace(synthetic_result(500, 0, 0), package_edges=edges))

    messages = build_messages(context, Lang.EN)

    assert len(messages[1]["content"]) <= MAX_PROMPT_CHARS


def test_system_prompt_explains_impact_and_package_dependencies() -> None:
    assert "impact" in SYSTEM_PROMPT
    assert "package_edges" in SYSTEM_PROMPT


def test_user_message_carries_no_paths_and_no_source_lines(circular_imports: Path) -> None:
    result = analyze_fixture(circular_imports)
    files = sorted(circular_imports.rglob("*.py"))
    source_lines = [
        line.strip()
        for file in files
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("def ")
    ]

    user_message = build_messages(build_context(result), Lang.EN)[1]["content"]

    assert source_lines
    assert str(circular_imports) not in user_message
    assert all(str(file) not in user_message for file in files)
    assert all(line not in user_message for line in source_lines)


def test_layer_violations_reach_the_ai_with_their_layer_names() -> None:
    violation = Finding(
        FindingKind.LAYER_VIOLATION,
        ("core.db", "web.views"),
        {"layer_from": "core", "layer_to": "web"},
    )

    summary = build_context(with_findings(synthetic_result(3, 0, 0), violation)).findings[0]

    assert (summary.kind, summary.modules) == ("layer_violation", ["core.db", "web.views"])
    assert summary.evidence == {"layer_from": "core", "layer_to": "web"}


def test_system_prompt_explains_layer_violations() -> None:
    assert "layer_violation" in SYSTEM_PROMPT
    assert "lower layer" in SYSTEM_PROMPT


def test_system_prompt_says_cycles_and_tangles_are_import_time() -> None:
    assert "at import time" in SYSTEM_PROMPT
    assert "TYPE_CHECKING" in SYSTEM_PROMPT


def test_context_serializes_distribution_findings_with_their_fix() -> None:
    root = Path(__file__).parent.parent / "fixtures" / "distributions_monorepo"
    context = build_context(analyze_fixture(root))
    assert context.finding_counts["undeclared_dependency"] == 1
    (undeclared,) = [f for f in context.findings if f.kind == "undeclared_dependency"]
    assert undeclared.evidence["requirement"] == '"core>=2.3.0"'


def test_system_prompt_explains_distribution_findings() -> None:
    prompt = SYSTEM_PROMPT
    assert "undeclared_dependency" in prompt
    assert "distribution names" in prompt


def test_context_lists_namespaces_and_excludes_them_from_module_count() -> None:
    root = Path(__file__).parent.parent / "fixtures" / "namespace_project"
    context = build_context(analyze_fixture(root))
    assert context.namespaces == ["app.types"]
    assert context.total_modules == 6


def test_system_prompt_explains_namespaces() -> None:
    assert "namespaces" in SYSTEM_PROMPT


def test_system_prompt_explains_missing_module_findings() -> None:
    assert "missing_module" in SYSTEM_PROMPT
