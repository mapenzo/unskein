"""Hold the verdicts of an untangle proof: what happened to each cut and to the whole plan."""

from dataclasses import dataclass
from enum import StrEnum


class ProofVerdict(StrEnum):
    """What the proof concluded about one cut.

    Attributes:
        PROVEN: The cut was applied to a copy and the dependency is gone.
        NOT_PROVEN: The cut was not applied; the reason says why.
        BROKEN: The cut was applied and it did not work.
    """

    PROVEN = "proven"
    NOT_PROVEN = "not_proven"
    BROKEN = "broken"


class ProofReason(StrEnum):
    """Why a cut is not proven or is broken.

    Attributes:
        NEEDS_DESIGN: The step needs a design decision (move a symbol, extract a module,
            restructure a package), not a mechanical edit.
        NO_DEFINER: BYPASS_FACADE names symbols, but no module of the project defines them.
        STAR_IMPORT: The statement is ``from x import *``, whose names are not written.
        NESTED_IMPORT: The import is not at module level.
        MULTIPLE_STATEMENTS: The import shares its line with another statement.
        ANNOTATIONS_EVALUATED: The names are read in annotations that run at import.
        READ_AT_IMPORT: The names are read while the module is being imported.
        READ_AT_RUNTIME: The names are read in a function, where a guard would not exist.
        NO_READER: Nothing reads the imported names, so there is nowhere to move it.
        NAME_REUSED: A function that reads the name also binds it, or it is rebound.
        EXPORTED: The name is in ``__all__``, or ``__all__`` cannot be read statically.
        INLINE_BODY: The statement sits in a one-line compound statement.
        RUNTIME_ANNOTATIONS: The module may read its annotations at run time (pydantic, typer,
            get_type_hints), so postponing them is unsafe.
        MUTABLE_ATTRIBUTE: A name read at import time through the package is not a class or
            function that nothing reassigns.
        UNREADABLE: The edited file would not parse, so the edit was discarded.
        EDGE_REMAINS: The cut was applied and the re-analysis still sees the dependency.
        IMPORT_FAILED: With --run, a module that imported before no longer imports.
    """

    NEEDS_DESIGN = "needs_design"
    NO_DEFINER = "no_definer"
    STAR_IMPORT = "star_import"
    NESTED_IMPORT = "nested_import"
    MULTIPLE_STATEMENTS = "multiple_statements"
    ANNOTATIONS_EVALUATED = "annotations_evaluated"
    READ_AT_IMPORT = "read_at_import"
    READ_AT_RUNTIME = "read_at_runtime"
    NO_READER = "no_reader"
    NAME_REUSED = "name_reused"
    EXPORTED = "exported"
    INLINE_BODY = "inline_body"
    RUNTIME_ANNOTATIONS = "runtime_annotations"
    MUTABLE_ATTRIBUTE = "mutable_attribute"
    UNREADABLE = "unreadable"
    EDGE_REMAINS = "edge_remains"
    IMPORT_FAILED = "import_failed"


@dataclass(frozen=True, slots=True)
class CutProof:
    """The verdict on one cut of the plan.

    Attributes:
        source: Module that imports.
        target: Module imported.
        verdict: What the proof concluded.
        reason: Why the cut is not proven or is broken; None when proven.
        detail: Extra evidence for the reason (a name, a line), possibly empty.
    """

    source: str
    target: str
    verdict: ProofVerdict
    reason: ProofReason | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """The outcome of importing one module in an isolated subprocess.

    Attributes:
        module: Dotted module name.
        ok: Whether the import succeeded.
        error: Last line of the error when it failed, possibly truncated.
        files: Project files named in the traceback, relative to the project root.
    """

    module: str
    ok: bool
    error: str = ""
    files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RunProof:
    """The result of importing the tangle's modules after the cuts.

    Attributes:
        modules: How many modules were imported before and after.
        importable: How many of them imported before the cuts (only those can regress).
        regressions: Modules that imported before and not after, tied to an edited file.
        unattributed: Regressions whose traceback names no edited file.
        seconds: Wall-clock time of the run layer.
    """

    modules: int
    importable: int
    regressions: tuple[ProbeResult, ...]
    unattributed: tuple[ProbeResult, ...]
    seconds: float


@dataclass(frozen=True, slots=True)
class ProofResult:
    """The proof of a whole untangle plan.

    Attributes:
        cuts: One verdict per cut of the plan, in plan order.
        tangles_after: Tangles left in the copy after the cuts.
        cycles_after: Cycles left in the copy (up to the report limit).
        cycles_after_truncated: Whether more cycles exist than ``cycles_after`` counts.
        run: The execution layer, or None when ``--run`` was not given.
    """

    cuts: tuple[CutProof, ...]
    tangles_after: int
    cycles_after: int
    cycles_after_truncated: bool
    run: RunProof | None = None

    def count(self, verdict: ProofVerdict) -> int:
        """Count the cuts that got a verdict.

        Args:
            verdict: The verdict to count.

        Returns:
            How many cuts have it.
        """
        return sum(1 for cut in self.cuts if cut.verdict is verdict)
