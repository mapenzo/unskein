import networkx as nx

from unskein.graph.impact import impact_radius


def test_impact_counts_direct_and_indirect_dependents() -> None:
    graph = nx.DiGraph([("app", "service"), ("service", "db")])

    assert impact_radius(graph, ["db", "service", "app"]) == {
        "db": 2,
        "service": 1,
        "app": 0,
    }


def test_impact_counts_each_dependent_once_in_a_diamond() -> None:
    graph = nx.DiGraph([("top", "left"), ("top", "right"), ("left", "base"), ("right", "base")])

    assert impact_radius(graph, ["base"]) == {"base": 3}


def test_impact_of_a_tangle_member_counts_the_other_members_and_never_itself() -> None:
    graph = nx.DiGraph([("a", "b"), ("b", "a"), ("c", "a")])

    assert impact_radius(graph, ["a", "b"]) == {"a": 2, "b": 2}


def test_modules_missing_from_the_graph_are_skipped() -> None:
    graph = nx.DiGraph([("a", "b")])

    assert impact_radius(graph, ["b", "ghost"]) == {"b": 1}


def test_duplicates_collapse_and_order_is_the_first_seen() -> None:
    graph = nx.DiGraph([("a", "b"), ("b", "c")])

    result = impact_radius(graph, ["c", "b", "c"])

    assert list(result.items()) == [("c", 2), ("b", 1)]


def test_no_modules_gives_no_impact() -> None:
    assert impact_radius(nx.DiGraph([("a", "b")]), []) == {}
