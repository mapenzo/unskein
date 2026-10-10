import ast

from unskein.graph.proof import ProofReason
from unskein.graph.smells import Smell, base_knows_subclass, config_snapshot

BASE = ast.parse("from app.child import Child\n\n\nclass Base:\n    kinds = (Child,)\n")
CHILD = ast.parse("from app.base import Base\n\n\nclass Child(Base):\n    pass\n")
FACADE = ast.parse(
    "from .conf import Settings\nfrom .x import helper\n\nmax_tokens = 100\n"
    "retries: int = 3\n\n\ndef make(): ...\n\n\nclass Thing: ...\n"
)


def test_a_base_that_imports_its_own_subclass_is_a_smell() -> None:
    assert base_knows_subclass(BASE, CHILD, ("Child",)) == Smell(
        ProofReason.BASE_KNOWS_SUBCLASS, "Base <- Child"
    )


def test_a_class_with_an_unrelated_base_is_not_a_smell() -> None:
    other = ast.parse("class Child(Other):\n    pass\n")
    assert base_knows_subclass(BASE, other, ("Child",)) is None


def test_only_the_imported_classes_count() -> None:
    assert base_knows_subclass(BASE, CHILD, ("Other",)) is None


def test_a_plainly_assigned_name_read_at_import_is_a_snapshot() -> None:
    assert config_snapshot(FACADE, ["max_tokens", "retries"]) == Smell(
        ProofReason.CONFIG_SNAPSHOT, "max_tokens, retries"
    )


def test_functions_classes_and_imports_are_not_snapshots() -> None:
    assert config_snapshot(FACADE, ["make", "Thing", "helper", "Settings"]) is None


def test_a_name_the_facade_does_not_bind_is_not_a_snapshot() -> None:
    assert config_snapshot(FACADE, ["missing"]) is None


def test_a_name_that_is_also_defined_or_imported_is_not_a_snapshot() -> None:
    facade = ast.parse("from .x import level\nlevel = 1\n\nsize = 1\n\n\ndef size(): ...\n")
    assert config_snapshot(facade, ["level", "size"]) is None
