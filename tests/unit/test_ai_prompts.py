import json
import re
from pathlib import Path

import networkx as nx
import pathspec
import pytest

from unskein.ai.models import AIContext, AIReport, Problem
from unskein.ai.prompts import (
    MAX_CYCLE_MEMBERS_IN_PROMPT,
    MAX_CYCLES_IN_PROMPT,
    MAX_MODULES_IN_PROMPT,
    MAX_PROMPT_CHARS,
    MAX_TANGLE_MEMBERS_IN_PROMPT,
    MAX_TANGLES_IN_PROMPT,
    SYSTEM_PROMPT,
    build_context,
    build_messages,
    ground_report,
)
from unskein.graph.metrics import AnalysisResult, analyze, compute_coupling
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


def test_code_snippets_are_cleared_until_v02() -> None:
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
