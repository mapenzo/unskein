"""Dependencies between the distributions of a project: uses, rules 6-9 and installability."""

from collections import Counter, defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath

import networkx as nx

from unskein.graph.findings import Evidence, Finding, FindingKind
from unskein.parsers.models import (
    DistributionInfo,
    ImportEdge,
    ImportKind,
    ManifestStyle,
    ParseResult,
)

PATH_SEPARATOR = "/"
NAME_SEPARATOR = "."
PROJECT_TABLE = "[project] dependencies"
SETUP_CFG_TABLE = "[options] install_requires"
POETRY_TABLE = "[tool.poetry.dependencies]"
TABLES = {
    ManifestStyle.PROJECT: PROJECT_TABLE,
    ManifestStyle.SETUP_CFG: SETUP_CFG_TABLE,
    ManifestStyle.POETRY: POETRY_TABLE,
}
POETRY_ANY_VERSION = "*"
MAX_UNPACKAGED_TARGETS = 5
LIST_SEPARATOR = ", "
FIX_ADD = "add_dependency"
FIX_PROMOTE = "promote_or_guard"
FIX_PACKAGE = "package_or_move"
FIX_CUT = "cut_edge"
BLOCKER_ARROW = "→"
# Separates the two ends of an edge to cut in the evidence: "a → b".
EDGE_ARROW = " → "
MIN_CYCLE_SIZE = 2
# Severity for the "installable alone?" blocker: unpackaged code, then undeclared, then optional.
BLOCKER_ORDER = (
    FindingKind.UNPACKAGED_IMPORT,
    FindingKind.UNDECLARED_DEPENDENCY,
    FindingKind.OPTIONAL_REQUIRED,
)


class ImportUse(StrEnum):
    """How an import is used, which decides what breaks without its target.

    Attributes:
        REQUIRED: Runs when the module is imported, unguarded.
        LAZY: Runs when a function is called, unguarded.
        GUARDED: Inside a ``try`` or ``suppress`` for import errors: optional by contract.
    """

    REQUIRED = "required"
    LAZY = "lazy"
    GUARDED = "guarded"


class DependencyStatus(StrEnum):
    """What a distribution declares about another it imports.

    Attributes:
        REQUIRED: Declared in its required dependencies.
        OPTIONAL: Declared only in extras.
        UNDECLARED: Not declared as a dependency (at most listed in a dependency group,
            which is never installed with the package).
        UNKNOWN: Its dependencies cannot be read (dynamic, ``setup.py`` only).
    """

    REQUIRED = "required"
    OPTIONAL = "optional"
    UNDECLARED = "undeclared"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class UseCounts:
    """How many import statements of each use, and where the first of each is.

    Attributes:
        required: Required uses.
        lazy: Lazy uses.
        guarded: Guarded uses.
        first: First location (``path:line``, relative to the project) per use, in
            ``ImportUse`` order; a use without statements has none.
    """

    required: int = 0
    lazy: int = 0
    guarded: int = 0
    first: tuple[tuple[ImportUse, str], ...] = ()

    def first_of(self, use: ImportUse) -> str | None:
        """Return where the first statement of one use is.

        Args:
            use: The use asked about.

        Returns:
            Its ``path:line``, or None when the use has no statement.
        """
        return dict(self.first).get(use)

    @property
    def breaking(self) -> int:
        """Return the uses that fail without the target: required plus lazy."""
        return self.required + self.lazy

    @property
    def first_breaking(self) -> str | None:
        """Return where the first breaking use is: a required one, else a lazy one."""
        return self.first_of(ImportUse.REQUIRED) or self.first_of(ImportUse.LAZY)


@dataclass(frozen=True, slots=True)
class DistributionEdge:
    """One distribution importing another, with what it declares about it.

    Attributes:
        source: Importing distribution.
        target: Imported distribution.
        counts: Uses behind the edge.
        status: What the source declares about the target.
        extras: Extras that declare the target, sorted, when optional.
        groups: Dependency groups that list the target, sorted, when undeclared.
    """

    source: str
    target: str
    counts: UseCounts
    status: DependencyStatus
    extras: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UnpackagedUse:
    """A distribution importing code that no distribution ships.

    Attributes:
        source: Importing distribution.
        package: First segment of the imported modules.
        counts: Uses behind it.
        targets: Imported modules, sorted.
        directory: Deepest directory holding every imported file, relative to the project,
            with a trailing ``/``; the file itself when it sits at the project root.
    """

    source: str
    package: str
    counts: UseCounts
    targets: tuple[str, ...]
    directory: str


@dataclass(frozen=True, slots=True)
class DistributionSummary:
    """Whether a distribution can be installed alone, and what it really uses.

    Attributes:
        name: Distribution name.
        modules: Modules it ships.
        uses: Distributions it imports, sorted.
        installable: Whether it has no rule 6-8 finding as source; None when its
            dependencies are unknown.
        blocker: ``path:line → target`` of the most severe problem, when not installable.
    """

    name: str
    modules: int
    uses: tuple[str, ...]
    installable: bool | None
    blocker: str | None


@dataclass(frozen=True, slots=True)
class DistributionAnalysis:
    """Everything the distribution rules found.

    Attributes:
        edges: Edges between distributions, sorted by (source, target).
        findings: Findings of rules 6-9, by kind order then modules.
        summaries: One summary per named distribution, sorted by name.
    """

    edges: list[DistributionEdge]
    findings: list[Finding]
    summaries: list[DistributionSummary]


@dataclass(slots=True)
class _Counter:
    """Mutable tally of the uses behind one edge, frozen into ``UseCounts`` at the end.

    Attributes:
        counts: Statements per use.
        first: First location per use.
    """

    counts: dict[ImportUse, int] = field(default_factory=lambda: defaultdict(int))
    first: dict[ImportUse, str] = field(default_factory=dict)

    def add(self, use: ImportUse, location: str) -> None:
        """Count one statement, keeping the first location of its use.

        Args:
            use: How the statement is used.
            location: Where it is (``path:line``); callers feed them in code order.
        """
        self.counts[use] += 1
        self.first.setdefault(use, location)

    def freeze(self) -> UseCounts:
        """Return the immutable counts.

        Returns:
            The tally as ``UseCounts``.
        """
        return UseCounts(
            self.counts[ImportUse.REQUIRED],
            self.counts[ImportUse.LAZY],
            self.counts[ImportUse.GUARDED],
            tuple((use, self.first[use]) for use in ImportUse if use in self.first),
        )


@dataclass(slots=True)
class _Collector:
    """Accumulators for the imports that cross a distribution boundary.

    Attributes:
        edges: Uses per (source distribution, target distribution).
        unpackaged: Uses per (source distribution, first segment of unpackaged code).
        unpackaged_targets: Imported unpackaged modules per the same key.
    """

    edges: dict[tuple[str, str], _Counter] = field(default_factory=lambda: defaultdict(_Counter))
    unpackaged: dict[tuple[str, str], _Counter] = field(
        default_factory=lambda: defaultdict(_Counter)
    )
    unpackaged_targets: dict[tuple[str, str], set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )


def import_use(edge: ImportEdge) -> ImportUse | None:
    """Classify an import by what breaks without its target.

    Args:
        edge: An internal import.

    Returns:
        Its use; None for ``TYPE_CHECKING`` imports, which never run.
    """
    if edge.kind is ImportKind.TYPE_CHECKING:
        return None
    if edge.is_guarded:
        return ImportUse.GUARDED
    return ImportUse.REQUIRED if edge.kind is ImportKind.MODULE else ImportUse.LAZY


def _relative(path: Path, root: Path | None) -> str:
    """Return a path as POSIX, relative to the project root when it lies under it.

    Args:
        path: File path.
        root: Absolute project directory, if known.

    Returns:
        The relative POSIX path, or the path as given.
    """
    absolute = path.absolute()
    if root is not None and absolute.is_relative_to(root):
        return absolute.relative_to(root).as_posix()
    return path.as_posix()


def _location(relative: str, line: int | None) -> str:
    """Return ``path:line`` for an import statement.

    Args:
        relative: Source file, relative to the project root.
        line: Line of the statement, if known.

    Returns:
        The location; without ``:line`` when the line is unknown.
    """
    return relative if line is None else f"{relative}:{line}"


def _collect(result: ParseResult, scripts: Collection[str]) -> _Collector:
    """Tally every import from a named distribution into another or into unpackaged code.

    Imports inside one distribution, ``TYPE_CHECKING`` imports, imports of unparsed files
    no named distribution ships, of scripts and of path-named files are left out; scripts
    are never sources.

    Args:
        result: Parsed project.
        scripts: Unpackaged modules nothing imports.

    Returns:
        The tallies.
    """
    # Unparsed files (too large, syntax errors) still belong to their distribution.
    distribution_of: dict[str, str | None] = dict(result.module_distributions)
    distribution_of.update((module.name, module.distribution) for module in result.modules)
    # Namespace packages have no file: their distribution and packaging come from their modules.
    for namespace in result.namespaces:
        distribution_of.setdefault(namespace, None)
    packaged = {module.name for module in result.modules if module.is_packaged}
    packaged.update(result.module_distributions)
    packaged.update(name for name, shipped in result.namespaces.items() if shipped)
    # Sorted by relative POSIX path, so "first" is the same on every platform; computed
    # once per module (Path.relative_to is slow on tens of thousands of imports).
    sources = sorted(
        (_relative(module.file_path, result.project_root), module)
        for module in result.modules
        if module.distribution is not None and module.name not in scripts
    )
    collector = _Collector()
    for relative, module in sources:
        source = module.distribution
        for edge in sorted(module.imports, key=lambda e: e.line_number or 0):
            use = None if edge.is_external else import_use(edge)
            if use is None or edge.target not in distribution_of:
                continue
            target = distribution_of[edge.target]
            if target == source:
                continue
            location = _location(relative, edge.line_number)
            if target is not None:
                collector.edges[source, target].add(use, location)
            elif edge.target in packaged:
                # Shipped by a distribution without a name: a dependency unskein cannot name.
                continue
            elif edge.target not in scripts and PATH_SEPARATOR not in edge.target:
                key = (source, edge.target.split(NAME_SEPARATOR, 1)[0])
                collector.unpackaged[key].add(use, location)
                collector.unpackaged_targets[key].add(edge.target)
    return collector


def _target_files(name: str, files: Mapping[str, Path]) -> list[Path]:
    """Return the file of a module, or the files under a namespace package.

    Args:
        name: Imported module or namespace package.
        files: Source file per parsed module.

    Returns:
        The files that make up the target.
    """
    if name in files:
        return [files[name]]
    prefix = f"{name}{NAME_SEPARATOR}"
    return [path for module, path in sorted(files.items()) if module.startswith(prefix)]


def _common_directory(paths: list[Path], root: Path | None) -> str:
    """Return the deepest directory holding every given file, relative to the project.

    Args:
        paths: Source files of the imported unpackaged modules.
        root: Absolute project directory, if known.

    Returns:
        The directory with a trailing ``/``; the file itself when it sits at the root.
    """
    # Compared part by part, not with os.path.commonpath, which joins with "\\" on Windows.
    parents = [PurePosixPath(_relative(path, root)).parent.parts for path in paths]
    common: list[str] = []
    for parts in zip(*parents, strict=False):
        if len(set(parts)) > 1:
            break
        common.append(parts[0])
    if not common:
        return _relative(paths[0], root)
    return f"{PATH_SEPARATOR.join(common)}{PATH_SEPARATOR}"


def _status(
    info: DistributionInfo, target: str
) -> tuple[DependencyStatus, tuple[str, ...], tuple[str, ...]]:
    """Return what a distribution declares about another one.

    Args:
        info: The importing distribution.
        target: Name of the imported distribution.

    Returns:
        The status, the extras that declare it when optional, and the dependency groups
        that list it when undeclared.
    """
    if info.requires is None:
        return DependencyStatus.UNKNOWN, (), ()
    if target in info.requires:
        return DependencyStatus.REQUIRED, (), ()
    extras = tuple(name for name, names in info.optional if target in names)
    if extras:
        return DependencyStatus.OPTIONAL, extras, ()
    groups = tuple(name for name, names in info.groups if target in names)
    return DependencyStatus.UNDECLARED, (), groups


def _requirement(target: DistributionInfo | None, name: str, style: ManifestStyle) -> str:
    """Return the requirement to copy into a manifest, in that manifest's syntax.

    Args:
        target: The imported distribution, when it is named.
        name: Its name.
        style: Syntax of the manifest being fixed.

    Returns:
        ``"name>=version"`` (or ``"name"``); for Poetry ``name = ">=version"`` (or ``"*"``).
    """
    version = target.version if target is not None else None
    if style is ManifestStyle.POETRY:
        constraint = f">={version}" if version is not None else POETRY_ANY_VERSION
        return f'{name} = "{constraint}"'
    if version is not None:
        return f'"{name}>={version}"'
    return f'"{name}"'


def _manifest(info: DistributionInfo, root: Path | None) -> str:
    """Return the manifest of a distribution relative to the project root.

    Args:
        info: The distribution.
        root: Absolute project directory, if known.

    Returns:
        Its manifest path; empty when it has none.
    """
    return "" if info.manifest is None else _relative(info.manifest, root)


def _first_any(counts: UseCounts) -> str:
    """Return where the first use is: a breaking one, else a guarded one.

    Args:
        counts: Uses behind an edge.

    Returns:
        The location; empty when there is no use.
    """
    return counts.first_breaking or counts.first_of(ImportUse.GUARDED) or ""


@dataclass(frozen=True, slots=True)
class _Context:
    """What the rules read besides the edges.

    Attributes:
        infos: Named distributions by name.
        root: Absolute project directory, if known.
    """

    infos: dict[str, DistributionInfo]
    root: Path | None


def _undeclared(edges: list[DistributionEdge], context: _Context) -> list[Finding]:
    """Apply rule 6: a distribution imports another it does not declare.

    Args:
        edges: Edges between distributions, sorted.
        context: Distributions and project root.

    Returns:
        One finding per undeclared edge with breaking uses.
    """
    findings = []
    for edge in edges:
        if edge.status is not DependencyStatus.UNDECLARED or edge.counts.breaking == 0:
            continue
        source = context.infos[edge.source]
        evidence: Evidence = {
            "required": edge.counts.required,
            "lazy": edge.counts.lazy,
            "guarded": edge.counts.guarded,
            "first": edge.counts.first_breaking or "",
            "fix": FIX_ADD,
            "manifest": _manifest(source, context.root),
            "table": TABLES[source.style],
            "requirement": _requirement(context.infos.get(edge.target), edge.target, source.style),
        }
        if edge.groups:
            evidence["groups"] = LIST_SEPARATOR.join(edge.groups)
        findings.append(
            Finding(FindingKind.UNDECLARED_DEPENDENCY, (edge.source, edge.target), evidence)
        )
    return findings


def _optional_required(edges: list[DistributionEdge], context: _Context) -> list[Finding]:
    """Apply rule 7: a distribution imports at load time one it only declares in an extra.

    Args:
        edges: Edges between distributions, sorted.
        context: Distributions and project root.

    Returns:
        One finding per optional edge with required uses.
    """
    findings = []
    for edge in edges:
        if edge.status is not DependencyStatus.OPTIONAL or edge.counts.required == 0:
            continue
        evidence: Evidence = {
            "required": edge.counts.required,
            "lazy": edge.counts.lazy,
            "guarded": edge.counts.guarded,
            "extras": LIST_SEPARATOR.join(edge.extras),
            "first": edge.counts.first_of(ImportUse.REQUIRED) or "",
            "fix": FIX_PROMOTE,
            "manifest": _manifest(context.infos[edge.source], context.root),
        }
        findings.append(
            Finding(FindingKind.OPTIONAL_REQUIRED, (edge.source, edge.target), evidence)
        )
    return findings


def _unpackaged(uses: list[UnpackagedUse]) -> list[Finding]:
    """Apply rule 8: a distribution imports code that no distribution ships.

    Args:
        uses: Imports of unpackaged code, sorted.

    Returns:
        One finding per use with breaking imports.
    """
    findings = []
    for use in uses:
        if use.counts.breaking == 0:
            continue
        evidence: Evidence = {
            "required": use.counts.required,
            "lazy": use.counts.lazy,
            "guarded": use.counts.guarded,
            "targets": LIST_SEPARATOR.join(use.targets[:MAX_UNPACKAGED_TARGETS]),
            "first": use.counts.first_breaking or "",
            "fix": FIX_PACKAGE,
            "directory": use.directory,
        }
        findings.append(Finding(FindingKind.UNPACKAGED_IMPORT, (use.source, use.package), evidence))
    return findings


def _cut_key(edge: DistributionEdge) -> tuple[int, int, str, str]:
    """Rank the edges of a cycle: the cheapest to cut first.

    Args:
        edge: An edge inside the cycle.

    Returns:
        Breaking uses, all uses, then the names, so ties are deterministic.
    """
    counts = edge.counts
    return (counts.breaking, counts.breaking + counts.guarded, edge.source, edge.target)


def _cuts(inside: list[DistributionEdge]) -> list[DistributionEdge]:
    """Pick edges to cut until a group of distributions has no cycle left, cheapest first.

    Cutting one edge of a group of three or more distributions may leave a smaller cycle,
    so the cheapest edge of each remaining group is cut until none is left.

    Args:
        inside: Edges between the members of one group, sorted.

    Returns:
        The edges to cut, in the order they were picked.
    """
    remaining = list(inside)
    cuts: list[DistributionEdge] = []
    while True:
        graph = nx.DiGraph((edge.source, edge.target) for edge in remaining)
        cyclic = [g for g in nx.strongly_connected_components(graph) if len(g) >= MIN_CYCLE_SIZE]
        if not cyclic:
            return cuts
        candidates = [e for e in remaining if any(e.source in g and e.target in g for g in cyclic)]
        cut = min(candidates, key=_cut_key)
        cuts.append(cut)
        remaining.remove(cut)


def _cycles(edges: list[DistributionEdge]) -> list[Finding]:
    """Apply rule 9: distributions that depend on each other, with the edges to cut.

    Args:
        edges: Edges between distributions, sorted.

    Returns:
        One finding per group of mutually dependent distributions, sorted by members.
    """
    graph = nx.DiGraph((edge.source, edge.target) for edge in edges)
    groups = sorted(tuple(sorted(group)) for group in nx.strongly_connected_components(graph))
    findings = []
    for members in groups:
        if len(members) < MIN_CYCLE_SIZE:
            continue
        cuts = _cuts([e for e in edges if e.source in members and e.target in members])
        evidence: Evidence = {
            "fix": FIX_CUT,
            "cuts": LIST_SEPARATOR.join(f"{e.source}{EDGE_ARROW}{e.target}" for e in cuts),
            "cut_breaking": sum(e.counts.breaking for e in cuts),
            "cut_guarded": sum(e.counts.guarded for e in cuts),
            "cut_first": _first_any(cuts[0].counts),
        }
        findings.append(Finding(FindingKind.DISTRIBUTION_CYCLE, members, evidence))
    return findings


def _summaries(
    result: ParseResult, edges: list[DistributionEdge], findings: list[Finding]
) -> list[DistributionSummary]:
    """Tell, per named distribution, whether it installs alone and what it uses.

    Args:
        result: Parsed project.
        edges: Edges between distributions, sorted.
        findings: Findings of rules 6-9.

    Returns:
        One summary per named distribution, sorted by name.
    """
    modules = Counter(m.distribution for m in result.modules if m.distribution is not None)
    summaries = []
    for info in sorted(result.distributions, key=lambda i: i.name):
        uses = tuple(sorted(e.target for e in edges if e.source == info.name))
        blocking = [
            f
            for kind in BLOCKER_ORDER
            for f in findings
            if f.kind is kind and f.modules[0] == info.name
        ]
        if blocking:
            first = blocking[0]
            blocker = f"{first.evidence['first']} {BLOCKER_ARROW} {first.modules[1]}"
            summaries.append(
                DistributionSummary(info.name, modules[info.name], uses, False, blocker)
            )
            continue
        installable = None if info.requires is None else True
        summaries.append(
            DistributionSummary(info.name, modules[info.name], uses, installable, None)
        )
    return summaries


def analyze_distributions(result: ParseResult, scripts: Collection[str]) -> DistributionAnalysis:
    """Cross what each distribution declares with how its imports are used.

    Args:
        result: Parsed project, re-exports resolved.
        scripts: Unpackaged modules nothing imports.

    Returns:
        Edges between distributions, findings of rules 6-9 and one summary per
        named distribution; empty when the project has no named distribution.
    """
    infos = {info.name: info for info in result.distributions}
    if not infos:
        return DistributionAnalysis([], [], [])
    collector = _collect(result, scripts)
    edges = []
    for (source, target), counter in sorted(collector.edges.items()):
        if source in infos and target in infos:
            status, extras, groups = _status(infos[source], target)
            edges.append(DistributionEdge(source, target, counter.freeze(), status, extras, groups))
    files = {module.name: module.file_path for module in result.modules}
    uses = []
    for (source, package), counter in sorted(collector.unpackaged.items()):
        if source in infos:
            targets = tuple(sorted(collector.unpackaged_targets[source, package]))
            paths = [path for target in targets for path in _target_files(target, files)]
            directory = _common_directory(paths, result.project_root)
            uses.append(UnpackagedUse(source, package, counter.freeze(), targets, directory))
    context = _Context(infos, result.project_root)
    findings = [
        *_undeclared(edges, context),
        *_optional_required(edges, context),
        *_unpackaged(uses),
        *_cycles(edges),
    ]
    return DistributionAnalysis(edges, findings, _summaries(result, edges, findings))
