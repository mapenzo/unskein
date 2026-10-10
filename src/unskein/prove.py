"""Prove an untangle plan: apply its cuts to a copy of the project and check each one."""

import dataclasses
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from unskein.graph.metrics import analyze, find_cycles, find_tangles
from unskein.graph.proof import CutProof, ProofReason, ProofResult, ProofVerdict
from unskein.graph.steps import StepKind
from unskein.graph.untangle import Cut, Edge, UntanglePlan
from unskein.parsers.discovery import detect_encoding
from unskein.parsers.layout import MANIFEST_NAMES
from unskein.parsers.rewrite import Move, MoveKind, rewrite_source
from unskein.scan import ScanContext, discover_project, parse_sources, resolve_parsed
from unskein.untangle import untangle_scope

WORKSPACE_PREFIX = "unskein-prove-"
COPY_DIR = "after"
MOVE_KINDS = {StepKind.LAZY: MoveKind.LAZY, StepKind.TYPE_CHECKING: MoveKind.TYPE_CHECKING}
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


def _planned_refusal(cut: Cut) -> ProofReason | None:
    """Tell why a cut cannot be applied mechanically, before reading any file.

    Args:
        cut: A cut of the plan.

    Returns:
        The reason, or None when its step can be rewritten.
    """
    if cut.step in DESIGN_STEPS:
        return ProofReason.NEEDS_DESIGN
    if cut.step is StepKind.BYPASS_FACADE:
        return ProofReason.NO_DEFINER if cut.evidence.symbols else ProofReason.WHOLE_MODULE_IMPORT
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


def copy_project(context: ScanContext, destination: Path) -> None:
    """Copy the discovered files, and the manifests that name their distributions.

    Args:
        context: A prepared scan.
        destination: Directory that becomes the copy's root.

    Raises:
        ProofUnavailable: If a file cannot be copied.
        UnskeinError: If the path is not a directory or holds no Python files.
    """
    root = context.root
    wanted: set[Path] = set()
    for path in discover_project(context):
        wanted.add(path)
        wanted.update(_manifests_above(path, root))
    try:
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


def _rewrite_file(
    context: ScanContext, path: Path, cuts: list[Cut], copy_root: Path
) -> tuple[list[Cut], dict[Edge, CutProof]]:
    """Apply the cuts of one file to its copy, all in one pass.

    Args:
        context: A prepared scan.
        path: The original file.
        cuts: The cuts whose import statements live in it.
        copy_root: Root of the copy.

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
    moves = [Move(MOVE_KINDS[cut.step], cut.evidence.lines) for cut in cuts]
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
    context: ScanContext, cuts: list[Cut], copy_root: Path
) -> tuple[list[Cut], dict[Edge, CutProof]]:
    """Apply every cut that can be applied mechanically to the copy.

    Args:
        context: A prepared scan.
        cuts: Every cut of the plan.
        copy_root: Root of the copy.

    Returns:
        The cuts that were applied, and the verdicts of all the others.

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
    applied: list[Cut] = []
    for path, file_cuts in by_file.items():
        done, refused = _rewrite_file(context, path, file_cuts, copy_root)
        applied.extend(done)
        settled.update(refused)
    return applied, settled


def _reanalyze(context: ScanContext, copy_root: Path, *, all_edges: bool) -> nx.DiGraph:
    """Analyze the edited copy as the original was analyzed.

    Args:
        context: The scan of the original project.
        copy_root: Root of the copy.
        all_edges: Whether lazy and type-only imports count too.

    Returns:
        The graph whose tangles `untangle` plans, for the copy.

    Raises:
        UnskeinError: If the copy holds no Python files.
    """
    copy_context = dataclasses.replace(context, root=copy_root)
    parsed = resolve_parsed(parse_sources(copy_context), copy_context)
    return untangle_scope(analyze(parsed, copy_context.findings).graph, all_edges=all_edges)


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
        UnskeinError: If the path is not a directory or holds no Python files.
    """
    cuts = [cut for tangle in plan.tangles for cut in tangle.cuts]
    try:
        with tempfile.TemporaryDirectory(prefix=WORKSPACE_PREFIX) as workspace:
            copy_root = Path(workspace) / COPY_DIR / context.root.resolve().name
            copy_project(context, copy_root)
            applied, verdicts = _apply_cuts(context, cuts, copy_root)
            scope = _reanalyze(context, copy_root, all_edges=plan.all_edges)
    except OSError as error:
        raise ProofUnavailable(str(error)) from error
    for cut in applied:
        edge = (cut.source, cut.target)
        if edge in scope.edges:
            verdicts[edge] = CutProof(
                cut.source, cut.target, ProofVerdict.BROKEN, ProofReason.EDGE_REMAINS
            )
        else:
            verdicts[edge] = CutProof(cut.source, cut.target, ProofVerdict.PROVEN)
    cycles, truncated = find_cycles(scope)
    return ProofResult(
        cuts=tuple(verdicts[(cut.source, cut.target)] for cut in cuts),
        tangles_after=len(find_tangles(scope)),
        cycles_after=len(cycles),
        cycles_after_truncated=truncated,
    )
