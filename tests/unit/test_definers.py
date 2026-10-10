from collections.abc import Callable
from pathlib import Path

import pytest

from unskein.graph.definers import DefinerIndex, build_definer_index
from unskein.scan import parse_sources, resolve_parsed
from unskein.untangle import UntangleOptions, prepare_untangle

MakeProject = Callable[[dict[str, str]], Path]

DEEP = {
    "pkg/__init__.py": "from .mid import Thing\n",
    "pkg/mid.py": "from .deep import Thing\n",
    "pkg/deep.py": "class Thing: ...\n\n\ndef helper(): ...\n",
}
GUARDED = "try:\n    from .mid import Thing\nexcept ImportError:\n    Thing = None\n"


def index_of(root: Path) -> DefinerIndex:
    context = prepare_untangle(UntangleOptions(path=root), env={})
    return build_definer_index(resolve_parsed(parse_sources(context), context), None)


def test_the_definer_is_found_through_a_chain_of_reexports(make_project: MakeProject) -> None:
    assert index_of(make_project(DEEP)).definer("pkg", "Thing") == "pkg.deep"


def test_a_function_has_a_definer(make_project: MakeProject) -> None:
    files = dict(DEEP) | {"pkg/__init__.py": "from .deep import helper\n"}
    assert index_of(make_project(files)).definer("pkg", "helper") == "pkg.deep"


@pytest.mark.parametrize(
    ("changes", "name"),
    [
        ({"pkg/deep.py": "Thing = object()\n"}, "Thing"),
        ({"pkg/other.py": "import pkg\n\npkg.Thing = None\n"}, "Thing"),
        ({"pkg/other.py": "import pkg\n\ndel pkg.Thing\n"}, "Thing"),
        ({"pkg/other.py": "import pkg\n\nsetattr(pkg, 'Thing', None)\n"}, "Thing"),
        (
            {"pkg/__init__.py": GUARDED},
            "Thing",
        ),
        ({"pkg/__init__.py": "from .deep import Thing\nfrom .mid import Thing\n"}, "Thing"),
        ({"pkg/__init__.py": "from .deep import helper as Thing\n"}, "Thing"),
        ({"pkg/__init__.py": "class Thing: ...\n"}, "Thing"),
        ({"pkg/Thing.py": "x = 1\n"}, "Thing"),
        ({"pkg/deep.py": "class Thing: ...\n\n\nclass Thing: ...\n"}, "Thing"),
    ],
    ids=[
        "assigned_not_defined",
        "attribute_store",
        "attribute_delete",
        "setattr_call",
        "guarded",
        "bound_twice",
        "renamed",
        "defined_in_the_facade",
        "submodule_of_that_name",
        "defined_twice",
    ],
)
def test_a_name_that_is_not_stable_has_no_definer(
    make_project: MakeProject, changes: dict[str, str], name: str
) -> None:
    files = dict(DEEP) | changes
    assert index_of(make_project(files)).definer("pkg", name) is None


def test_a_guarded_reexport_has_no_definer(make_project: MakeProject) -> None:
    files = dict(DEEP) | {"pkg/__init__.py": GUARDED}
    assert index_of(make_project(files)).definer("pkg", "Thing") is None


def test_an_unknown_name_has_no_definer(make_project: MakeProject) -> None:
    assert index_of(make_project(DEEP)).definer("pkg", "Missing") is None


@pytest.mark.parametrize(
    "files",
    [
        {
            "pkg/__init__.py": "from .errors import Thing\nfrom .deep import *\n",
            "pkg/errors.py": "class Thing: ...\n",
            "pkg/deep.py": "__all__ = ['Thing']\n\n\nclass Thing: ...\n",
        },
        {
            "pkg/__init__.py": "from .errors import Thing\nfrom os.path import *\n",
            "pkg/errors.py": "class Thing: ...\n",
        },
    ],
    ids=["project_star_after", "external_star_after"],
)
def test_a_star_import_after_the_binding_leaves_no_definer(
    make_project: MakeProject, files: dict[str, str]
) -> None:
    assert index_of(make_project(files)).definer("pkg", "Thing") is None


def test_a_star_import_before_the_binding_keeps_the_definer(make_project: MakeProject) -> None:
    files = {
        "pkg/__init__.py": "from .deep import *\nfrom .errors import Thing\n",
        "pkg/errors.py": "class Thing: ...\n",
        "pkg/deep.py": "__all__ = ['Thing']\n\n\nclass Thing: ...\n",
    }
    assert index_of(make_project(files)).definer("pkg", "Thing") == "pkg.errors"


def test_a_definer_outside_the_facade_package_is_refused(make_project: MakeProject) -> None:
    files = {
        "pkg/__init__.py": "from other.impl import Thing\n",
        "other/__init__.py": "",
        "other/impl.py": "class Thing: ...\n",
    }
    assert index_of(make_project(files)).definer("pkg", "Thing") is None


def test_a_facade_that_replaces_itself_in_sys_modules_has_no_definer(
    make_project: MakeProject,
) -> None:
    files = dict(DEEP) | {
        "pkg/__init__.py": (
            "import sys\nfrom .deep import Thing\n\nsys.modules[__name__] = object()\n"
        )
    }
    assert index_of(make_project(files)).definer("pkg", "Thing") is None


def test_a_relative_import_above_the_top_level_package_is_not_followed(
    make_project: MakeProject,
) -> None:
    files = dict(DEEP) | {"pkg/mid.py": "from ...deep import Thing\n"}
    assert index_of(make_project(files)).definer("pkg", "Thing") is None
