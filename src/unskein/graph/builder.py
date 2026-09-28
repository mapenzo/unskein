import networkx as nx

from unskein.parsers.models import ParseResult


def build_graph(result: ParseResult) -> nx.DiGraph:
    """Internal modules only as nodes; external imports are dropped."""
    raise NotImplementedError
