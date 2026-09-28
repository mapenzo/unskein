from dataclasses import replace

from unskein.parsers.models import ParseResult, ReExport

MAX_RESOLUTION_DEPTH = 10

ReExportIndex = dict[tuple[str, str], str]


def build_reexport_index(re_exports: list[ReExport]) -> ReExportIndex:
    return {(re.exporting_module, re.symbol_name): re.original_module for re in re_exports}


def resolve_target(
    module: str,
    symbol: str | None,
    index: ReExportIndex,
    path: list[str] | None = None,
) -> tuple[str, list[str]]:
    if path is None:
        path = []

    if symbol is None or (module, symbol) not in index:
        return module, []
    if module in path:
        # Canonical (sorted) members so every entry point into the cycle yields the same text.
        members = ", ".join(f"'{m}'" for m in sorted(path[path.index(module) :]))
        return module, [f"Re-export cycle for '{symbol}' between {members}, stopping resolution"]
    if len(path) >= MAX_RESOLUTION_DEPTH:
        return module, [f"Max re-export depth exceeded for '{symbol}' at '{module}'"]

    path.append(module)
    return resolve_target(index[(module, symbol)], symbol, index, path)


def resolve_indirection(result: ParseResult) -> ParseResult:
    """Point internal symbol imports at the defining module; returns a new ParseResult."""
    index = build_reexport_index(result.re_exports)
    warnings = dict.fromkeys(result.warnings)
    modules = []
    for module in result.modules:
        imports = []
        for edge in module.imports:
            if edge.is_external or edge.symbol_name is None:
                imports.append(edge)
                continue
            target, edge_warnings = resolve_target(edge.target, edge.symbol_name, index)
            warnings.update(dict.fromkeys(edge_warnings))
            if target != edge.source:
                imports.append(replace(edge, target=target))
        modules.append(replace(module, imports=imports))
    return replace(result, modules=modules, warnings=list(warnings))
