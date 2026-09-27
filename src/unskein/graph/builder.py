import networkx as nx

from unskein.parsers.base import ParseResult


def build_graph(result: ParseResult) -> nx.DiGraph:
    """Internal modules only as nodes; external imports are dropped."""
    raise NotImplementedError
