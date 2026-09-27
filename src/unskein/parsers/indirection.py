from unskein.parsers.base import ParseResult, ReExport

MAX_RESOLUTION_DEPTH = 10

ReExportIndex = dict[tuple[str, str], str]


def build_reexport_index(re_exports: list[ReExport]) -> ReExportIndex:
    return {(re.exporting_module, re.symbol_name): re.original_module for re in re_exports}


def resolve_target(
    module: str,
    symbol: str | None,
    index: ReExportIndex,
    visited: set[str] | None = None,
) -> tuple[str, list[str]]:
    if visited is None:
        visited = set()
    warnings: list[str] = []

    if symbol is None or (module, symbol) not in index:
        return module, warnings
    if module in visited:
        warnings.append(f"Re-export cycle detected at '{module}', stopping resolution")
        return module, warnings
    if len(visited) >= MAX_RESOLUTION_DEPTH:
        warnings.append(f"Max re-export depth exceeded at '{module}'")
        return module, warnings

    visited.add(module)
    return resolve_target(index[(module, symbol)], symbol, index, visited)


def resolve_indirection(result: ParseResult) -> ParseResult:
    """Rewrite internal ImportEdge.target through re-export chains; externals untouched."""
    raise NotImplementedError
