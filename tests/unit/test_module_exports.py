import ast

from unskein.parsers.exports import module_exports


def exports_of(source: str):
    """Compute what a module exposes to a star import.

    Args:
        source: Python source of the module.

    Returns:
        Its ``ModuleExports``.
    """
    return module_exports(ast.parse(source))


def test_literal_all_is_used_as_is() -> None:
    result = exports_of("__all__ = ['A', 'b']\nA = 1\nb = 2\nC = 3\n")
    assert (result.names, result.declares_all) == (("A", "b"), True)


def test_literal_all_can_be_extended() -> None:
    result = exports_of("__all__ = ('A',)\n__all__ += ['B']\n")
    assert (result.names, result.declares_all) == (("A", "B"), True)


def test_dynamic_all_falls_back_to_public_names() -> None:
    result = exports_of("__all__ = names()\nA = 1\n_b = 2\n")
    assert (result.names, result.declares_all) == (("A",), False)


def test_public_top_level_names_without_all() -> None:
    source = (
        "import os\nimport pkg.sub\nfrom x import y as z, w\nfrom q import *\n"
        "def f(): inner = 1\nasync def g(): pass\nclass K:\n    attr = 1\n"
        "A, (B, _c) = 1, (2, 3)\nD: int = 4\n_private = 5\n"
        "try:\n    E = 1\nexcept ImportError:\n    F = 2\n"
        "if True:\n    G = 1\nelse:\n    H = 2\n"
    )
    result = exports_of(source)
    assert result.names == ("A", "B", "D", "E", "F", "G", "H", "K", "f", "g", "os", "pkg", "w", "z")
    assert result.declares_all is False
