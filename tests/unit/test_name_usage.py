import ast

import pytest

from unskein.parsers.models import ImportEdge
from unskein.parsers.usage import collect_name_usage


def usage_of(source: str, name: str = "p"):
    """Collect how ``name`` is used in a source snippet.

    Args:
        source: Python source to analyze.
        name: Imported name to track.

    Returns:
        The ``NameUsage`` of that name.
    """
    return collect_name_usage(ast.parse(source), [name])[name]


def test_attribute_chains_are_collected_whole() -> None:
    usage = usage_of("x = p.a.b.c\ny = p.d(1)\n")
    assert usage.chains == {"a.b.c", "d"}
    assert usage.escapes is False


def test_chain_stops_where_the_value_is_not_a_plain_attribute() -> None:
    assert usage_of("p.make().other\n").chains == {"make"}


def test_uses_inside_functions_classes_decorators_and_annotations_count() -> None:
    source = "@p.deco\ndef f(x: p.T) -> p.R:\n    return p.v\nclass C(p.Base):\n    y = p.w\n"
    assert usage_of(source).chains == {"deco", "T", "R", "v", "Base", "w"}


@pytest.mark.parametrize(
    "source",
    ["f(p)\n", "x = p\n", "p = None\n", "p.x = 1\n", "del p.x\n", "for p in items:\n    pass\n"],
    ids=["argument", "alias", "rebound", "attribute_store", "attribute_delete", "loop_target"],
)
def test_bare_use_rebinding_and_attribute_writes_escape(source: str) -> None:
    assert usage_of(source).escapes is True


def test_chains_and_escape_are_reported_together() -> None:
    usage = usage_of("p.a\ng(p)\n")
    assert usage.chains == {"a"}
    assert usage.escapes is True


def test_other_names_are_ignored() -> None:
    usage = usage_of("q.a\nr(q)\n")
    assert (usage.chains, usage.escapes) == (set(), False)


def test_import_statements_are_not_uses() -> None:
    assert usage_of("import p\nfrom x import p\n").escapes is False


def test_edge_fields_default_to_an_unanalyzed_import() -> None:
    edge = ImportEdge("a", "b", False)
    assert (edge.accessed, edge.escapes) == ((), False)


def test_quoted_annotation_records_its_chain() -> None:
    usage = usage_of("def f(x: 'p.Engine', y: 'list[p.Other]'): ...\n")
    assert usage.chains == {"Engine", "Other"}
    assert usage.escapes is False


def test_unparsable_string_mentioning_the_name_escapes() -> None:
    assert usage_of("x = 'p.Engine('\n").escapes is True


def test_string_not_mentioning_the_name_is_ignored() -> None:
    usage = usage_of("x = 'hello p'\ny = 'pp.Engine'\n")
    assert usage.chains == set()
    assert usage.escapes is False
