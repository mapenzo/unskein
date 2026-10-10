"""Prove an untangle plan: apply its cuts to a copy of the project and check each one."""

import ast
import dataclasses
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from unskein.errors import ErrorKey, UnskeinError
from unskein.graph.metrics import analyze, find_cycles, find_tangles
from unskein.graph.proof import (
    CutProof,
    ProbeResult,
    ProofReason,
    ProofResult,
    ProofVerdict,
    RunProof,
)
from unskein.graph.steps import DEFERRED_CONTEXTS, StepKind
from unskein.graph.untangle import Cut, Edge, UntanglePlan
from unskein.parsers.discovery import detect_encoding
from unskein.parsers.layout import MANIFEST_NAMES
from unskein.parsers.rewrite import Move, MoveKind, rewrite_source
from unskein.pipeline import worker_count
from unskein.probe import PROBE_TIMEOUT_SECONDS, ProbeJob, import_roots, run_probes
from unskein.proof_facts import ProjectFacts
from unskein.scan import ScanContext, discover_project, parse_sources, resolve_parsed
from unskein.untangle import untangle_scope

WORKSPACE_PREFIX = "unskein-prove-"
COPY_DIR = "after"
BEFORE_DIR = "before"
SKIPPED_DIRECTORIES = (
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    ".eggs",
)
DESIGN_STEPS = frozenset(
    {StepKind.MOVE_SYMBOL, StepKind.EXTRACT_SHARED, StepKind.PACKAGE_STRUCTURE}
)


@dataclass(frozen=True)
class ProveOptions:
    """What the user asked the proof to do.

    Attributes:
        run: Whether to also import the tangle's modules before and after the cuts.
        python: Interpreter for that run; None means the one running unskein.
    """

    run: bool = False
    python: Path | None = None


class ProofUnavailable(Exception):
    """The proof could not be built, for a reason outside the plan (disk, permissions).

    Args:
        detail: What failed, language-neutral.
    """

    def __init__(self, detail: str) -> None:
        """Keep the detail for the report.

        Args:
            detail: What failed, language-neutral.
        """
        super().__init__(detail)
        self.detail = detail


SMELLABLE_REASONS = frozenset(
    {ProofReason.NEEDS_DESIGN, ProofReason.READ_AT_IMPORT, ProofReason.MUTABLE_ATTRIBUTE}
)


def _name_smells(cuts: list[Cut], verdicts: dict[Edge, CutProof], *, facts: ProjectFacts) -> None:
    """Replace a generic reason by the design smell behind it, where there is one.

    Args:
        cuts: Every cut of the plan.
        verdicts: Verdicts settled so far; updated in place.
        facts: Project facts; only read for the cuts that can carry a smell.
    """
    for cut in cuts:
        edge = (cut.source, cut.target)
        found = verdicts.get(edge)
        if found is None or found.reason not in SMELLABLE_REASONS:
            continue
        smell = facts.smell(cut)
        if smell is not None:
            verdicts[edge] = CutProof(
                cut.source, cut.target, ProofVerdict.NOT_PROVEN, smell.reason, smell.detail
            )


def _planned_refusal(cut: Cut) -> ProofReason | None:
    """Tell why a cut cannot be applied mechanically, before reading any file.

    Args:
        cut: A cut of the plan.

    Returns:
        The reason, or None when its step can be rewritten.
    """
    if cut.step in DESIGN_STEPS:
        return ProofReason.NEEDS_DESIGN
    if cut.step is StepKind.BYPASS_FACADE and cut.evidence.symbols:
        return ProofReason.NO_DEFINER
    if cut.evidence.file_path is None or not cut.evidence.lines:
        return ProofReason.UNREADABLE
    return None


def _relative(path: Path, root: Path) -> Path | None:
    """Return a project file's path relative to the project root.

    Args:
        path: A discovered file.
        root: The project root.

    Returns:
        The relative path, or None when the file is outside the root.
    """
    try:
        return path.relative_to(root)
    except ValueError:
        try:
            return path.resolve().relative_to(root.resolve())
        except ValueError:
            return None


def _manifests_above(path: Path, root: Path) -> list[Path]:
    """List the manifests between a file's directory and the project root.

    Args:
        path: A discovered file.
        root: The project root.

    Returns:
        The manifest files that exist there, since they name each file's distribution.
    """
    found: list[Path] = []
    folder = path.parent
    while True:
        found.extend(folder / name for name in MANIFEST_NAMES if (folder / name).is_file())
        if folder == root or folder == folder.parent:
            return found
        folder = folder.parent


def copy_project(context: ScanContext, destination: Path, *, whole_tree: bool = False) -> None:
    """Copy the project: the discovered files, or the whole tree for ``--run``.

    The static proof only needs the sources and the manifests that name their
    distributions. Importing modules also needs whatever they read when they load (data
    files, templates), so ``--run`` copies everything except version-control data,
    virtual environments and caches.

    Args:
        context: A prepared scan.
        destination: Directory that becomes the copy's root.
        whole_tree: Whether to copy every file instead of the discovered ones.

    Raises:
        ProofUnavailable: If a file cannot be copied.
        UnskeinError: If the path is not a directory or holds no Python files.
    """
    root = context.root
    files = discover_project(context)
    try:
        if whole_tree:
            shutil.copytree(
                root,
                destination,
                symlinks=True,
                ignore=shutil.ignore_patterns(*SKIPPED_DIRECTORIES),
                dirs_exist_ok=True,
            )
        wanted: set[Path] = set()
        for path in files:
            wanted.add(path)
            wanted.update(_manifests_above(path, root))
        for path in sorted(wanted):
            relative = _relative(path, root)
            if relative is None:
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    except OSError as error:
        raise ProofUnavailable(str(error)) from error


def _refused(cuts: list[Cut], reason: ProofReason) -> dict[Edge, CutProof]:
    """Mark every cut as not proven for one reason.

    Args:
        cuts: Cuts of one file.
        reason: Why none could be applied.

    Returns:
        A not-proven verdict per cut.
    """
    return {
        (cut.source, cut.target): CutProof(cut.source, cut.target, ProofVerdict.NOT_PROVEN, reason)
        for cut in cuts
    }


def _move_for(cut: Cut, tree: ast.Module, facts: ProjectFacts) -> Move:
    """Build the rewrite move that applies a cut.

    Args:
        cut: A cut whose step can be rewritten.
        tree: Syntax tree of the importing module.
        facts: Project facts; the definer index is only built for a bypass.

    Returns:
        The move; a postponing cut also adds ``from __future__ import annotations``, and
        goes under ``TYPE_CHECKING`` only when every read is an annotation.
    """
    evidence = cut.evidence
    if cut.step is StepKind.BYPASS_FACADE:
        return Move(MoveKind.BYPASS, evidence.lines, definers=facts.definers_read(cut, tree))
    postpone = cut.step is StepKind.POSTPONE_ANNOTATIONS
    type_only = cut.step is StepKind.TYPE_CHECKING or (
        postpone and evidence.contexts <= DEFERRED_CONTEXTS
    )
    kind = MoveKind.TYPE_CHECKING if type_only else MoveKind.LAZY
    return Move(kind, evidence.lines, postpone=postpone)


def _rewrite_file(
    context: ScanContext, path: Path, cuts: list[Cut], *, copy_root: Path, facts: ProjectFacts
) -> tuple[list[Cut], dict[Edge, CutProof]]:
    """Apply the cuts of one file to its copy, all in one pass.

    Args:
        context: A prepared scan.
        path: The original file.
        cuts: The cuts whose import statements live in it.
        copy_root: Root of the copy.
        facts: Project facts shared by every file.

    Returns:
        The cuts that were applied, and the verdicts of those that were refused.

    Raises:
        ProofUnavailable: If the edited copy cannot be written.
    """
    relative = _relative(path, context.root)
    encoding = detect_encoding(path, context.analysis.default_encoding)
    try:
        text = path.read_bytes().decode(encoding)
    except (OSError, UnicodeDecodeError, LookupError):
        return [], _refused(cuts, ProofReason.UNREADABLE)
    if relative is None:
        return [], _refused(cuts, ProofReason.UNREADABLE)
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return [], _refused(cuts, ProofReason.UNREADABLE)
    moves = [_move_for(cut, tree, facts) for cut in cuts]
    result = rewrite_source(text, moves)
    applied: list[Cut] = []
    refused: dict[Edge, CutProof] = {}
    for cut, refusal in zip(cuts, result.refusals, strict=True):
        if refusal is None:
            applied.append(cut)
        else:
            refused[(cut.source, cut.target)] = CutProof(
                cut.source, cut.target, ProofVerdict.NOT_PROVEN, ProofReason(refusal.value)
            )
    if result.source != text:
        try:
            (copy_root / relative).write_bytes(result.source.encode(encoding))
        except OSError as error:
            raise ProofUnavailable(str(error)) from error
    return applied, refused


def _apply_cuts(
    context: ScanContext, cuts: list[Cut], copy_root: Path, *, facts: ProjectFacts
) -> tuple[dict[Path, list[Cut]], dict[Edge, CutProof]]:
    """Apply every cut that can be applied mechanically to the copy.

    Args:
        context: A prepared scan.
        cuts: Every cut of the plan.
        copy_root: Root of the copy.
        facts: Project facts shared by every file.

    Returns:
        The cuts that were applied, grouped by the original file they edit, and the
        verdicts of all the others.

    Raises:
        ProofUnavailable: If an edited file cannot be written.
    """
    settled: dict[Edge, CutProof] = {}
    by_file: dict[Path, list[Cut]] = {}
    for cut in cuts:
        reason = _planned_refusal(cut)
        if reason is None and cut.evidence.file_path is not None:
            by_file.setdefault(cut.evidence.file_path, []).append(cut)
        else:
            settled.update(_refused([cut], reason or ProofReason.UNREADABLE))
    applied: dict[Path, list[Cut]] = {}
    for path, file_cuts in by_file.items():
        done, refused = _rewrite_file(context, path, file_cuts, copy_root=copy_root, facts=facts)
        if done:
            applied[path] = done
        settled.update(refused)
    return applied, settled


def _reanalyze(
    context: ScanContext, copy_root: Path, *, all_edges: bool
) -> tuple[nx.DiGraph, dict[str, Path]]:
    """Analyze the edited copy as the original was analyzed.

    Args:
        context: The scan of the original project.
        copy_root: Root of the copy.
        all_edges: Whether lazy and type-only imports count too.

    Returns:
        The graph whose tangles `untangle` plans, for the copy, and the path of every
        parsed module relative to the copy root.

    Raises:
        UnskeinError: If the copy holds no Python files.
    """
    copy_context = dataclasses.replace(context, root=copy_root)
    parsed = resolve_parsed(parse_sources(copy_context), copy_context)
    modules: dict[str, Path] = {}
    for module in parsed.modules:
        relative = _relative(module.file_path, copy_root)
        if relative is not None:
            modules[module.name] = relative
    scope = untangle_scope(analyze(parsed, copy_context.findings).graph, all_edges=all_edges)
    return scope, modules


def resolve_python(python: Path | None) -> Path:
    """Pick the interpreter that runs the imports of ``--run``.

    Args:
        python: The interpreter the user asked for, or None for the running one.

    Returns:
        The interpreter path.

    Raises:
        UnskeinError: If the given interpreter does not exist.
    """
    if python is None:
        return Path(sys.executable)
    if not python.is_file():
        raise UnskeinError(ErrorKey.PYTHON_NOT_FOUND, {"path": str(python)})
    return python


@dataclass(frozen=True, slots=True)
class _RunInputs:
    """What the execution layer needs, gathered once.

    Attributes:
        python: Interpreter for every import.
        before_root: Root of the unedited copy.
        after_root: Root of the edited copy.
        modules: Module name to its path relative to either root.
        members: The modules of the tangles, sorted.
        edited: Edited file of the copy, resolved, to the cuts applied in it.
        workers: How many imports run at the same time.
    """

    python: Path
    before_root: Path
    after_root: Path
    modules: dict[str, Path]
    members: list[str]
    edited: dict[Path, list[Cut]]
    workers: int


def _probe_root(inputs: _RunInputs, root: Path) -> dict[str, ProbeResult]:
    """Import every tangle member from one copy.

    Args:
        inputs: What the run needs.
        root: Root of the copy to import from.

    Returns:
        The outcome per member.
    """
    job = ProbeJob(
        inputs.python,
        root,
        import_roots(inputs.modules, root),
        PROBE_TIMEOUT_SECONDS,
        inputs.workers,
    )
    return run_probes(job, inputs.members)


def _attributed_cuts(inputs: _RunInputs, result: ProbeResult) -> list[Cut]:
    """Find the cuts whose edited file appears in a failed import's traceback.

    Args:
        inputs: What the run needs.
        result: A failed import.

    Returns:
        The cuts applied in the edited files the traceback names.
    """
    found: list[Cut] = []
    for name in result.files:
        found.extend(inputs.edited.get(Path(name).resolve(), []))
    return found


def _run_layer(inputs: _RunInputs) -> tuple[RunProof, dict[Edge, CutProof]]:
    """Import the tangle's modules before and after the cuts and compare.

    A module that did not import before cannot regress. A regression is tied to a cut
    when its traceback goes through a file that the cut edited.

    Args:
        inputs: What the run needs.

    Returns:
        The run summary and a broken verdict for every cut tied to a regression.
    """
    started = time.perf_counter()
    before = _probe_root(inputs, inputs.before_root)
    after = _probe_root(inputs, inputs.after_root)
    regressions: list[ProbeResult] = []
    unattributed: list[ProbeResult] = []
    broken: dict[Edge, CutProof] = {}
    for name in inputs.members:
        if not before[name].ok or after[name].ok:
            continue
        culprits = _attributed_cuts(inputs, after[name])
        (regressions if culprits else unattributed).append(after[name])
        for cut in culprits:
            broken.setdefault(
                (cut.source, cut.target),
                CutProof(
                    cut.source,
                    cut.target,
                    ProofVerdict.BROKEN,
                    ProofReason.IMPORT_FAILED,
                    f"{name}: {after[name].error}",
                ),
            )
    run = RunProof(
        modules=len(inputs.members),
        importable=sum(1 for name in inputs.members if before[name].ok),
        regressions=tuple(regressions),
        unattributed=tuple(unattributed),
        seconds=time.perf_counter() - started,
    )
    return run, broken


def _static_verdict(cut: Cut, scope: nx.DiGraph) -> CutProof:
    """Judge an applied cut by whether the re-analysis still sees its edge.

    Args:
        cut: A cut that was applied to the copy.
        scope: The re-analyzed graph of the copy.

    Returns:
        ``PROVEN`` when the dependency is gone, else ``BROKEN`` with ``EDGE_REMAINS``.
    """
    if (cut.source, cut.target) in scope.edges:
        return CutProof(cut.source, cut.target, ProofVerdict.BROKEN, ProofReason.EDGE_REMAINS)
    return CutProof(cut.source, cut.target, ProofVerdict.PROVEN)


def _edited_files(
    context: ScanContext, applied: dict[Path, list[Cut]], copy_root: Path
) -> dict[Path, list[Cut]]:
    """Map each edited file of the copy to the cuts applied in it.

    Args:
        context: A prepared scan.
        applied: Applied cuts by original file.
        copy_root: Root of the copy.

    Returns:
        The resolved path of every edited file of the copy.
    """
    edited: dict[Path, list[Cut]] = {}
    for path, done in applied.items():
        relative = _relative(path, context.root)
        if relative is not None:
            edited[(copy_root / relative).resolve()] = done
    return edited


def prove_plan(context: ScanContext, plan: UntanglePlan, options: ProveOptions) -> ProofResult:
    """Apply the plan's cuts to a copy of the project and check each one.

    The user's project is never modified: the copy lives in a temporary directory that
    is deleted afterwards.

    Args:
        context: A prepared scan.
        plan: The untangle plan to prove.
        options: Whether to also import the modules before and after.

    Returns:
        One verdict per cut, in plan order, and what is left of the tangles.

    Raises:
        ProofUnavailable: If the copy or the run cannot be done.
        UnskeinError: If the path is not a directory, holds no Python files, or the
            interpreter of ``--run`` does not exist.
    """
    cuts = [cut for tangle in plan.tangles for cut in tangle.cuts]
    python = resolve_python(options.python) if options.run else None
    try:
        with tempfile.TemporaryDirectory(prefix=WORKSPACE_PREFIX) as workspace:
            base = Path(workspace)
            copy_root = base / COPY_DIR / context.root.resolve().name
            copy_project(context, copy_root, whole_tree=python is not None)
            facts = ProjectFacts(context)
            applied, verdicts = _apply_cuts(context, cuts, copy_root, facts=facts)
            _name_smells(cuts, verdicts, facts=facts)
            scope, modules = _reanalyze(context, copy_root, all_edges=plan.all_edges)
            for done in applied.values():
                for cut in done:
                    verdicts[(cut.source, cut.target)] = _static_verdict(cut, scope)
            run = None
            if python is not None:
                before_root = base / BEFORE_DIR / copy_root.name
                copy_project(context, before_root, whole_tree=True)
                inputs = _RunInputs(
                    python,
                    before_root,
                    copy_root,
                    modules,
                    sorted({member for tangle in plan.tangles for member in tangle.members}),
                    _edited_files(context, applied, copy_root),
                    worker_count(context.analysis),
                )
                run, broken = _run_layer(inputs)
                verdicts.update(broken)
    except OSError as error:
        raise ProofUnavailable(str(error)) from error
    cycles, truncated = find_cycles(scope)
    return ProofResult(
        cuts=tuple(verdicts[(cut.source, cut.target)] for cut in cuts),
        tangles_after=len(find_tangles(scope)),
        cycles_after=len(cycles),
        cycles_after_truncated=truncated,
        run=run,
    )
