"""Prepare and build an untangle plan: the imports to cut to undo each tangle."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from unskein.graph.metrics import PACKAGE_INIT_FILE, analyze, find_tangles, import_time_graph
from unskein.graph.untangle import Edge, UntanglePlan, plan_tangles, simulate
from unskein.parsers.models import ImportKind, ParseResult
from unskein.parsers.usage import ImportEvidence, collect_import_evidence
from unskein.scan import ScanContext, ScanOptions, parse_project, prepare_scan

DEFAULT_MAX_TANGLES = 5


@dataclass(frozen=True)
class UntangleOptions:
    """What the user asked for in one ``untangle`` run.

    Attributes:
        path: Directory to analyze.
        lang: Requested output language.
        all_edges: Whether lazy and type-only imports count too (hidden coupling).
        max_tangles: How many tangles the report details, largest first.
    """

    path: Path
    lang: str | None = None
    all_edges: bool = False
    max_tangles: int = DEFAULT_MAX_TANGLES


def prepare_untangle(
    options: UntangleOptions,
    env: Mapping[str, str] | None = None,
    user_config: Path | None = None,
) -> ScanContext:
    """Load the configuration exactly as ``scan`` does, without the AI.

    Args:
        options: What the user asked for.
        env: Environment variables; None means ``os.environ``.
        user_config: User-wide config file; None means the default location.

    Returns:
        The prepared context.

    Raises:
        ConfigError: If a configuration file is invalid.
    """
    scan_options = ScanOptions(path=options.path, no_ai=True, lang=options.lang)
    return prepare_scan(scan_options, env=env, user_config=user_config)


def facade_own_names(parsed: ParseResult) -> dict[str, frozenset[str]]:
    """Map each package facade to the names it defines itself.

    A facade's own names are those it binds at module level that are neither re-exports
    of another project module nor its own submodules; importing them cannot bypass it.

    Args:
        parsed: The resolved parse result.

    Returns:
        The own names of each ``__init__.py`` module.
    """
    modules = {m.name for m in parsed.modules}
    re_exported: dict[str, set[str]] = {}
    for re_export in parsed.re_exports:
        re_exported.setdefault(re_export.exporting_module, set()).add(re_export.symbol_name)
    facades = {}
    for module in parsed.modules:
        if module.file_path.name != PACKAGE_INIT_FILE:
            continue
        borrowed = re_exported.get(module.name, set())
        facades[module.name] = frozenset(
            name
            for name in module.bound_names
            if name not in borrowed and f"{module.name}.{name}" not in modules
        )
    return facades


def names_imported_from(parsed: ParseResult) -> dict[str, frozenset[str]]:
    """Map each project module to the names other project modules import from it.

    Args:
        parsed: The resolved parse result.

    Returns:
        The names imported by name from each module that has any.
    """
    found: dict[str, set[str]] = {}
    for module in parsed.modules:
        for edge in module.imports:
            if not edge.is_external and edge.symbol_name is not None:
                found.setdefault(edge.target, set()).add(edge.symbol_name)
    return {name: frozenset(names) for name, names in found.items()}


def _keep_names_at_module_level(
    evidence: Mapping[Edge, ImportEvidence], imported_from: Mapping[str, frozenset[str]]
) -> dict[Edge, ImportEvidence]:
    """Drop the use contexts of imports that bind a name other modules import from the source.

    Moving such an import into a function or under ``TYPE_CHECKING`` removes the name
    from the source module at runtime, which breaks every module importing it from there.

    Args:
        evidence: Evidence per dependency.
        imported_from: Names other modules import from each module.

    Returns:
        The evidence, without contexts where the lazy and type-only steps would break others.
    """
    kept = {}
    for edge, found in evidence.items():
        if imported_from.get(edge[0], frozenset()).isdisjoint(found.bound_names):
            kept[edge] = found
        else:
            kept[edge] = replace(found, contexts=frozenset())
    return kept


def build_untangle_plan(context: ScanContext, *, all_edges: bool) -> UntanglePlan:
    """Analyze the project and plan the cuts of every tangle.

    Only the modules inside a tangle are read again for evidence.

    Args:
        context: A prepared context.
        all_edges: Whether lazy and type-only imports count too.

    Returns:
        The plan.

    Raises:
        UnskeinError: If the path is not a directory or holds no Python files.
    """
    parsed = parse_project(context)
    result = analyze(parsed, context.findings)
    scope = result.graph if all_edges else import_time_graph(result.graph)
    tangles = find_tangles(scope)
    facades = facade_own_names(parsed)
    kinds = set(ImportKind) if all_edges else {ImportKind.MODULE}
    pairs_by_source: dict[str, list[Edge]] = {}
    for members in tangles:
        for edge in scope.subgraph(members).edges:
            pairs_by_source.setdefault(edge[0], []).append(edge)
    evidence: dict[Edge, ImportEvidence] = {}
    for module in parsed.modules:
        if module.name in pairs_by_source:
            evidence.update(
                collect_import_evidence(
                    module,
                    pairs_by_source[module.name],
                    kinds=kinds,
                    encoding=context.analysis.default_encoding,
                )
            )
    evidence = _keep_names_at_module_level(evidence, names_imported_from(parsed))
    plans = plan_tangles(scope, tangles, evidence, facades=facades, all_edges=all_edges)
    cuts = [cut for plan in plans for cut in plan.cuts]
    return UntanglePlan(
        all_edges=all_edges,
        tangles=plans,
        simulation=simulate(scope, result.graph, cuts),
        hidden_tangles=len(result.hidden_tangles),
    )
