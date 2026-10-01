import networkx as nx
import pytest

from unskein.graph.packages import (
    ROOT_PACKAGE,
    PackageEdge,
    PackageMetrics,
    package_of,
    summarize_packages,
)


@pytest.mark.parametrize(
    ("module", "depth", "facades", "expected"),
    [
        ("core.db.engine", 1, (), "core"),
        ("core.db.engine", 2, (), "core.db"),
        ("core.db", 1, (), "core"),
        ("core", 1, ("core",), "core"),
        ("core.db", 2, ("core.db",), "core.db"),
        ("manage", 1, (), ROOT_PACKAGE),
        ("core.db", 2, (), ROOT_PACKAGE),
        ("a.b", 5, (), ROOT_PACKAGE),
    ],
)
def test_package_of_names_the_package_or_the_root(
    module: str, depth: int, facades: tuple[str, ...], expected: str
) -> None:
    assert package_of(module, depth, facades) == expected


def test_instability_of_a_package() -> None:
    assert PackageMetrics("web", 4, 1, 3).instability == 0.75
    assert PackageMetrics("lonely", 1, 0, 0).instability == 0.0


def test_packages_count_modules_and_distinct_packages_on_each_side() -> None:
    graph = nx.DiGraph(
        [
            ("web.views", "core.db"),
            ("web.forms", "core.db"),
            ("web.views", "web.forms"),
            ("core.db", "util.text"),
        ]
    )

    packages, edges = summarize_packages(graph, 1)

    assert packages == [
        PackageMetrics("core", 1, 1, 1),
        PackageMetrics("util", 1, 1, 0),
        PackageMetrics("web", 2, 0, 1),
    ]
    assert edges == [PackageEdge("web", "core", 2), PackageEdge("core", "util", 1)]


def test_imports_inside_one_package_are_not_package_dependencies() -> None:
    graph = nx.DiGraph([("a.x", "a.y"), ("a.y", "a.z")])

    packages, edges = summarize_packages(graph, 1)

    assert packages == [PackageMetrics("a", 3, 0, 0)]
    assert edges == []


def test_depth_two_keeps_subpackages_apart() -> None:
    graph = nx.DiGraph([("app.api.users", "app.db.models")])

    packages, edges = summarize_packages(graph, 2)

    assert [p.name for p in packages] == ["app.api", "app.db"]
    assert edges == [PackageEdge("app.api", "app.db", 1)]


def test_facades_and_plain_root_modules_are_labeled_correctly() -> None:
    graph = nx.DiGraph([("manage", "core"), ("core", "core.db")])

    packages, _ = summarize_packages(graph, 1, facades={"core"})

    assert {p.name: p.modules for p in packages} == {ROOT_PACKAGE: 1, "core": 2}


def test_empty_graph_gives_no_packages() -> None:
    assert summarize_packages(nx.DiGraph(), 1) == ([], [])


def test_one_package_projects_give_one_package_and_no_edges() -> None:
    graph = nx.DiGraph()
    graph.add_nodes_from(["only.a", "only.b"])

    assert summarize_packages(graph, 1) == ([PackageMetrics("only", 2, 0, 0)], [])


def test_order_is_by_coupling_then_name_and_by_imports_then_names() -> None:
    graph = nx.DiGraph([("b.x", "a.x"), ("c.x", "a.x"), ("c.y", "a.y")])

    packages, edges = summarize_packages(graph, 1)

    assert [p.name for p in packages] == ["a", "b", "c"]
    assert edges == [PackageEdge("c", "a", 2), PackageEdge("b", "a", 1)]
