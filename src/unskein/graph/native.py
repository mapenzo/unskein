"""The native boundary: how packaged code uses compiled extensions and stubs, and rule 11."""

from collections import Counter
from collections.abc import Collection, Iterable
from dataclasses import dataclass

import networkx as nx

from unskein.graph.distributions import ImportUse, import_use, relative_path
from unskein.graph.findings import Finding, FindingKind
from unskein.parsers.models import ParseResult, VirtualKind

MAX_LOCATIONS_SHOWN = 5
LIST_SEPARATOR = ", "
LINE_SEPARATOR = ":"
FIX_GUARD_OR_DROP_FALLBACK = "guard_or_drop_fallback"
# Counter key for TYPE_CHECKING imports, which have no ImportUse.
TYPE_ONLY = "type_only"


@dataclass(frozen=True, slots=True)
class NativeModule:
    """How packaged code uses one compiled extension or stub-only module.

    Attributes:
        name: Dotted module name.
        kind: ``COMPILED`` or ``STUB``.
        evidence: What proves it exists (paths, or ``pyproject.toml:line``).
        afferent: Modules of the graph that import it (its Ca); 0 when hidden.
        required: Unguarded imports that run at load time.
        lazy: Unguarded imports inside functions.
        guarded: Imports inside a ``try`` or ``suppress`` for import errors.
        type_only: Imports under ``TYPE_CHECKING``, which never run.
        unguarded: Every required or lazy import as ``path:line``, sorted.
        first_guarded: First guarded import as ``path:line``, if any.
    """

    name: str
    kind: VirtualKind
    evidence: tuple[str, ...]
    afferent: int
    required: int
    lazy: int
    guarded: int
    type_only: int
    unguarded: tuple[str, ...]
    first_guarded: str | None

    @property
    def works_without(self) -> bool:
        """Whether the packaged code runs without it: every use is guarded or type-only."""
        return not self.unguarded


def summarize_native(
    result: ParseResult, graph: nx.DiGraph, scripts: Collection[str]
) -> list[NativeModule]:
    """Tally how packaged code imports each compiled extension and stub-only module.

    Tests, scripts and other unpackaged code are left out: the boundary is about what
    breaks once the package is installed.

    Args:
        result: Parsed project, re-exports resolved.
        graph: Module graph, scripts excluded (gives each module's Ca).
        scripts: Unpackaged modules nothing imports.

    Returns:
        One entry per native module, sorted by name.
    """
    natives = {name for name, module in result.virtual.items() if module.kind.is_native}
    counts: dict[str, Counter[str]] = {name: Counter() for name in natives}
    unguarded: dict[str, list[str]] = {name: [] for name in natives}
    guarded: dict[str, list[str]] = {name: [] for name in natives}
    sources = sorted(
        (relative_path(module.file_path, result.project_root), module)
        for module in result.modules
        if module.is_packaged
        and module.name not in scripts
        and any(edge.target in natives for edge in module.imports)
    )
    for relative, module in sources:
        for edge in sorted(module.imports, key=lambda e: e.line_number or 0):
            if edge.is_external or edge.target not in natives:
                continue
            use = import_use(edge)
            counts[edge.target][use.value if use else TYPE_ONLY] += 1
            location = f"{relative}{LINE_SEPARATOR}{edge.line_number}"
            if use is ImportUse.GUARDED:
                guarded[edge.target].append(location)
            elif use is not None:
                unguarded[edge.target].append(location)
    return [
        NativeModule(
            name=name,
            kind=result.virtual[name].kind,
            evidence=result.virtual[name].evidence,
            afferent=graph.in_degree(name) if name in graph else 0,
            required=counts[name][ImportUse.REQUIRED.value],
            lazy=counts[name][ImportUse.LAZY.value],
            guarded=counts[name][ImportUse.GUARDED.value],
            type_only=counts[name][TYPE_ONLY],
            unguarded=tuple(unguarded[name]),
            first_guarded=guarded[name][0] if guarded[name] else None,
        )
        for name in sorted(natives)
    ]


def find_optional_native_required(natives: Iterable[NativeModule]) -> list[Finding]:
    """Apply rule 11: the code guards a native module in one place and not in another.

    Without any guarded use the extension is required on purpose and the code is
    coherent: no finding.

    Args:
        natives: The native boundary, from ``summarize_native``.

    Returns:
        One finding per native module with guarded and unguarded uses, sorted by name.
    """
    findings = []
    for native in natives:
        if native.first_guarded is None or not native.unguarded:
            continue
        evidence = {
            "kind": native.kind.value,
            "guarded": native.guarded,
            "first_guarded": native.first_guarded,
            "required": native.required,
            "lazy": native.lazy,
            "unguarded": LIST_SEPARATOR.join(native.unguarded[:MAX_LOCATIONS_SHOWN]),
            "unguarded_total": len(native.unguarded),
            "fix": FIX_GUARD_OR_DROP_FALLBACK,
        }
        findings.append(Finding(FindingKind.OPTIONAL_NATIVE_REQUIRED, (native.name,), evidence))
    return findings
