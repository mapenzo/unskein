"""Adversarial star import scenarios from the second review: {name: (files, entry)}."""

# Each source is one literal, kept as the review wrote it, so lines can be long.
# ruff: noqa: E501

REVIEW_SCENARIOS = {
    "call_before_rebind": (
        {
            "app/b.py": "X = 'b.X'\n",
            "app/m.py": "from app.b import *\ndef f():\n    return X\nprint(f())\nX = 'late'\n",
        },
        "import app.m",
    ),
    "lambda_before_rebind": (
        {
            "app/b.py": "X = 'b.X'\n",
            "app/m.py": "from app.b import *\ng = lambda: X\nprint(g())\nX = 'late'\n",
        },
        "import app.m",
    ),
    "class_method_called_before_rebind": (
        {
            "app/b.py": "X = 'b.X'\n",
            "app/m.py": "from app.b import *\nclass C:\n    def v(self):\n        return X\nprint(C().v())\nX = 'late'\n",
        },
        "import app.m",
    ),
    "annotation_only_after": (
        {
            "app/b.py": "X = 'b.X'\n",
            "app/m.py": "from app.b import *\nX: str\nprint(X)\n",
        },
        "import app.m",
    ),
    "base_annotation_only": (
        {
            "app/b.py": "X: int\nY = 1\n",
            "app/m.py": "from app.b import *\nprint(Y)\ndef f(X=None):\n    return X\n",
        },
        "import app.m",
    ),
    "base_deletes_name_string_key": (
        {
            "app/b.py": "value = 21\nCONST = value * 2\ndel value\n",
            "app/m.py": "from app.b import *\nd = {'value': CONST}\nprint(d)\n",
        },
        "import app.m",
    ),
    "base_type_checking_only": (
        {
            "app/c.py": "class Foo: pass\n",
            "app/b.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from app.c import Foo\nBAR = 1\n",
            "app/m.py": "from __future__ import annotations\nfrom app.b import *\ndef f(x: Foo) -> None:\n    pass\nprint(BAR)\n",
        },
        "import app.m",
    ),
    "base_conditional_platform": (
        {
            "app/b.py": "import sys\nif sys.platform == 'nonexistent':\n    WinThing = 1\nOK = 1\n",
            "app/m.py": "from app.b import *\nprint(OK)\ndef g():\n    WinThing = 2\n    return WinThing\n",
        },
        "import app.m",
    ),
    "importer_type_checking_same_import": (
        {
            "app/c.py": "class Foo: pass\n",
            "app/b.py": "from app.c import Foo\n",
            "app/m.py": "from typing import TYPE_CHECKING\nfrom app.b import *\nif TYPE_CHECKING:\n    from app.c import Foo\nprint(Foo)\n",
        },
        "import app.m",
    ),
    "importer_type_checking_from_base": (
        {
            "app/b.py": "class Params: pass\n",
            "app/m.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from app.b import Params\nfrom app.b import *\nprint(Params)\n",
        },
        "import app.m",
    ),
    "importer_lazy_same_import_plus_module_binding": (
        {
            "app/c.py": "class Foo: pass\n",
            "app/b.py": "from app.c import Foo\n",
            "app/m.py": "import sys\nfrom app.b import *\ntry:\n    from app.c import Foo\nexcept ImportError:\n    pass\nprint(Foo)\n",
        },
        "import app.m",
    ),
    "importlib_access": (
        {
            "app/b.py": "W = 'b.W'\n",
            "app/m.py": "from app.b import *\n",
            "app/user.py": "import importlib\nmod = importlib.import_module('app.m')\nprint(mod.W)\n",
        },
        "import app.user",
    ),
    "getattr_string": (
        {
            "app/b.py": "W = 'b.W'\n",
            "app/m.py": "from app.b import *\n",
            "app/user.py": "import app.m\nprint(getattr(app.m, 'W'))\n",
        },
        "import app.user",
    ),
    "sys_modules": (
        {
            "app/b.py": "W = 'b.W'\n",
            "app/m.py": "from app.b import *\n",
            "app/user.py": "import sys\nimport app.m\nprint(sys.modules['app.m'].W)\n",
        },
        "import app.user",
    ),
    "package_attribute_chain": (
        {
            "app/b.py": "W = 'b.W'\n",
            "app/m.py": "from app.b import *\n",
            "app/user.py": "import app\nimport app.m\nprint(app.m.W)\n",
        },
        "import app.user",
    ),
    "package_import_then_chain": (
        {
            "app/pkg/__init__.py": "from . import m\n",
            "app/pkg/b.py": "W = 'b.W'\n",
            "app/pkg/m.py": "from app.pkg.b import *\n",
            "app/user.py": "import app.pkg\nprint(app.pkg.m.W)\n",
        },
        "import app.user",
    ),
    "from_package_import_module_chain": (
        {
            "app/pkg/__init__.py": "from . import m\n",
            "app/pkg/b.py": "W = 'b.W'\n",
            "app/pkg/m.py": "from app.pkg.b import *\n",
            "app/user.py": "from app import pkg\nprint(pkg.m.W)\n",
        },
        "import app.user",
    ),
    "module_in_function_scope": (
        {
            "app/b.py": "W = 'b.W'\n",
            "app/m.py": "from app.b import *\n",
            "app/user.py": "def f():\n    import app.m as mm\n    return mm.W\nprint(f())\n",
        },
        "import app.user",
    ),
    "module_bound_twice_names": (
        {
            "app/b.py": "W = 'b.W'\n",
            "app/m.py": "from app.b import *\n",
            "app/user.py": "from app import m\ndef f():\n    m = 3\n    return m\nprint(m.W, f())\n",
        },
        "import app.user",
    ),
    "mock_patch_string": (
        {
            "app/b.py": "W = 'b.W'\n",
            "app/m.py": "from app.b import *\n",
            "app/user.py": "from unittest import mock\nwith mock.patch('app.m.W', 'patched'):\n    import app.m\n    print(app.m.W)\n",
        },
        "import app.user",
    ),
    "decorator_reads_before_rebind": (
        {
            "app/b.py": "def deco(f):\n    return f\n",
            "app/m.py": "from app.b import *\n@deco\ndef deco(f):\n    return f\nprint('ok')\n",
        },
        "import app.m",
    ),
    "default_arg_reads": (
        {
            "app/b.py": "X = 1\n",
            "app/m.py": "from app.b import *\ndef f(a=X):\n    return a\nX = 2\nprint(f())\n",
        },
        "import app.m",
    ),
    "comprehension_reads_before_rebind": (
        {
            "app/b.py": "X = 1\n",
            "app/m.py": "from app.b import *\nL = [X for _ in range(1)]\nX = 2\nprint(L)\n",
        },
        "import app.m",
    ),
    "global_in_function_reads_then_called": (
        {
            "app/b.py": "X = 1\n",
            "app/m.py": "from app.b import *\ndef bump():\n    global X\n    X = X + 1\nbump()\nprint(X)\nX = 0\n",
        },
        "import app.m",
    ),
    "other_module_reads_during_cycle": (
        {
            "app/b.py": "X = 'b.X'\n",
            "app/late.py": "from app.b import *\nimport app.other\nX = 'late'\n",
            "app/other.py": "from app.late import X\nprint(X)\n",
        },
        "import app.late",
    ),
    "partial_cycle_extra_name": (
        {
            "app/b.py": "Y = 1\nimport app.a\nX = 2\n",
            "app/a.py": "from app.b import *\nprint(Y)\ndef f():\n    return X\n",
        },
        "import app.b",
    ),
    "star_of_facade_package": (
        {
            "app/pkg/__init__.py": "from .impl import *\n",
            "app/pkg/impl.py": "A = 1\nB = 2\n",
            "app/m.py": "from app.pkg import *\nprint(A)\n",
        },
        "import app.m",
    ),
    "star_of_facade_with_all": (
        {
            "app/pkg/__init__.py": "from .impl import *\nfrom .impl import __all__\n",
            "app/pkg/impl.py": "__all__ = ['A']\nA = 1\nB = 2\n",
            "app/m.py": "from app.pkg import *\nprint(A)\n",
        },
        "import app.m",
    ),
    "submodule_loaded_elsewhere": (
        {
            "app/pkg/__init__.py": "X = 1\n",
            "app/pkg/sub.py": "def f():\n    return 'f'\n",
            "app/loader.py": "import app.pkg.sub\n",
            "app/m.py": "import app.loader\nfrom app.pkg import *\nprint(X, sub.f())\n",
        },
        "import app.m",
    ),
    "relative_star": (
        {
            "app/pkg/__init__.py": "",
            "app/pkg/b.py": "X = 1\n",
            "app/pkg/m.py": "from .b import *\nprint(X)\n",
        },
        "import app.pkg.m",
    ),
    "importer_all_reexports": (
        {
            "app/b.py": "X = 1\nY = 2\n",
            "app/m.py": "from app.b import *\n__all__ = ['X', 'Y']\n",
            "app/user.py": "from app.m import *\nprint(X, Y)\n",
        },
        "import app.user",
    ),
    "same_name_two_imports_one_alias_different": (
        {
            "app/c.py": "Foo = 'c'\n",
            "app/d.py": "Foo = 'd'\n",
            "app/b.py": "from app.c import Foo\n",
            "app/m.py": "from app.c import Foo\nfrom app.b import *\nprint(Foo)\n",
        },
        "import app.m",
    ),
    "base_same_import_but_rebinds_later": (
        {
            "app/c.py": "Foo = 'c'\n",
            "app/b.py": "from app.c import Foo\nFoo = 'b-own'\n",
            "app/m.py": "from app.c import Foo\nfrom app.b import *\nprint(Foo)\n",
        },
        "import app.m",
    ),
    "base_same_import_rebinds_in_function_global": (
        {
            "app/c.py": "Foo = 'c'\n",
            "app/b.py": "from app.c import Foo\ndef _init():\n    global Foo\n    Foo = 'b-own'\n_init()\n",
            "app/m.py": "from app.c import Foo\nfrom app.b import *\nprint(Foo)\n",
        },
        "import app.m",
    ),
    "base_same_import_rebinds_in_for": (
        {
            "app/c.py": "Foo = 'c'\n",
            "app/b.py": "from app.c import Foo\nfor Foo in ['b-loop']:\n    pass\n",
            "app/m.py": "from app.c import Foo\nfrom app.b import *\nprint(Foo)\n",
        },
        "import app.m",
    ),
    "importer_from_base_but_base_rebinds_later_via_star": (
        {
            "app/b.py": "Params = 'early'\n",
            "app/m.py": "from app.b import Params\nfrom app.b import *\nprint(Params)\n",
        },
        "import app.m",
    ),
    "import_dotted_vs_plain": (
        {
            "app/pkg/__init__.py": "",
            "app/pkg/x.py": "V = 'x'\n",
            "app/pkg/y.py": "V = 'y'\n",
            "app/b.py": "import app.pkg.x\nimport app.pkg.y\n",
            "app/m.py": "import app.pkg.x\nfrom app.b import *\nprint(app.pkg.y.V)\n",
        },
        "import app.m",
    ),
    "import_dotted_single_each": (
        {
            "app/pkg/__init__.py": "",
            "app/pkg/x.py": "V = 'x'\n",
            "app/pkg/y.py": "V = 'y'\n",
            "app/b.py": "import app.pkg.y\n",
            "app/m.py": "import app.pkg.y\nfrom app.b import *\nprint(app.pkg.y.V)\n",
        },
        "import app.m",
    ),
    "walrus_module_level": (
        {
            "app/b.py": "X = 1\n",
            "app/m.py": "from app.b import *\nprint(X)\n(X := 5)\n",
        },
        "import app.m",
    ),
    "match_binding": (
        {
            "app/b.py": "X = 1\n",
            "app/m.py": "from app.b import *\nprint(X)\nmatch 1:\n    case X:\n        pass\n",
        },
        "import app.m",
    ),
    "with_binding": (
        {
            "app/b.py": "X = 1\n",
            "app/m.py": "import contextlib\nfrom app.b import *\nprint(X)\nwith contextlib.nullcontext(3) as X:\n    pass\n",
        },
        "import app.m",
    ),
    "class_body_reads_before_rebind": (
        {
            "app/b.py": "X = 1\n",
            "app/m.py": "from app.b import *\nclass C:\n    y = X\nX = 2\nprint(C.y)\n",
        },
        "import app.m",
    ),
    "rebound_as_class_using_itself": (
        {
            "app/b.py": "class Base:\n    v = 'b'\n",
            "app/m.py": "from app.b import *\nclass Base(Base):\n    pass\nprint(Base.v)\n",
        },
        "import app.m",
    ),
    "rebound_assign_self": (
        {
            "app/b.py": "X = 'b'\n",
            "app/m.py": "from app.b import *\nX = X + '!'\nprint(X)\n",
        },
        "import app.m",
    ),
    "rebound_with_try_reads": (
        {
            "app/b.py": "X = 'b'\n",
            "app/m.py": "from app.b import *\ntry:\n    print(X)\nfinally:\n    pass\nX = 1\n",
        },
        "import app.m",
    ),
    "star_inside_class_body": (
        {
            "app/b.py": "X = 1\n",
            "app/m.py": "class C:\n    pass\nfrom app.b import *\nprint(X)\n",
        },
        "import app.m",
    ),
    "star_under_if": (
        {
            "app/b.py": "X = 1\n",
            "app/m.py": "import sys\nif sys:\n    from app.b import *\nprint(X)\n",
        },
        "import app.m",
    ),
    "eval_short": (
        {
            "app/b.py": "X = 1\n",
            "app/m.py": "from app.b import *\nprint(eval('X'))\n",
        },
        "import app.m",
    ),
    "fstring_reads": (
        {
            "app/b.py": "X = 1\n",
            "app/m.py": "from app.b import *\nprint(f'{X}')\n",
        },
        "import app.m",
    ),
    "star_of_module_with_dunder_names": (
        {
            "app/b.py": "__version__ = '1'\nX = 1\n",
            "app/m.py": "from app.b import *\nprint(X)\n",
        },
        "import app.m",
    ),
    "downstream_star_of_importer_dynamic": (
        {
            "app/b.py": "X = 1\nY = 2\n",
            "app/m.py": "from app.b import *\n",
            "app/user.py": "from app.m import *\nprint(Y)\n",
        },
        "import app.user",
    ),
    "module_passed_as_arg": (
        {
            "app/b.py": "W = 'b.W'\n",
            "app/m.py": "from app.b import *\n",
            "app/user.py": "import app.m as mm\ndef show(mod):\n    return mod.W\nprint(show(mm))\n",
        },
        "import app.user",
    ),
    "vars_of_module": (
        {
            "app/b.py": "W = 'b.W'\n",
            "app/m.py": "from app.b import *\n",
            "app/user.py": "from app import m\nprint(vars(m)['W'])\n",
        },
        "import app.user",
    ),
}
REVIEW_SCENARIOS.update(
    {
        "external_star_upstream": (
            {
                "app/m.py": "from os.path import *\nX = 1\n",
                "app/user.py": "from app.m import *\nprint(X, join('a', 'b'))\n",
            },
            "import app.user",
        ),
        "external_star_in_facade": (
            {
                "app/pkg/__init__.py": "from os.path import *\nfrom .impl import *\n",
                "app/pkg/impl.py": "A = 1\n",
                "app/user.py": "from app.pkg import *\nprint(A, join('a', 'b'))\n",
            },
            "import app.user",
        ),
        "importer_for_rebinding_before_star": (
            {
                "app/c.py": "Foo = 'c'\n",
                "app/b.py": "from app.c import Foo\n",
                "app/m.py": "from app.c import Foo\nfor Foo in ['loop']:\n    pass\nfrom app.b import *\nprint(Foo)\n",
            },
            "import app.m",
        ),
        "importer_global_rebinding_before_star": (
            {
                "app/c.py": "Foo = 'c'\n",
                "app/b.py": "from app.c import Foo\n",
                "app/m.py": "from app.c import Foo\ndef s():\n    global Foo\n    Foo = 'mine'\ns()\nfrom app.b import *\nprint(Foo)\n",
            },
            "import app.m",
        ),
        "base_with_rebinding": (
            {
                "app/c.py": "Foo = 'c'\n",
                "app/b.py": "import contextlib\nfrom app.c import Foo\nwith contextlib.nullcontext('b-with') as Foo:\n    pass\n",
                "app/m.py": "from app.c import Foo\nfrom app.b import *\nprint(Foo)\n",
            },
            "import app.m",
        ),
        "base_same_import_then_del": (
            {
                "app/c.py": "Foo = 'c'\n",
                "app/b.py": "from app.c import Foo\ndel Foo\nB = 1\n",
                "app/m.py": "Foo = 1\nfrom app.c import Foo\nfrom app.b import *\nprint(Foo, B)\n",
            },
            "import app.m",
        ),
        "base_import_in_try_else_fallback": (
            {
                "app/c.py": "Foo = 'c'\n",
                "app/b.py": "try:\n    from app.nope import Foo\nexcept ImportError:\n    Foo = 'fallback'\n",
                "app/m.py": "from app.c import Foo\nfrom app.b import *\nprint(Foo)\n",
            },
            "import app.m",
        ),
        "base_import_under_false_if": (
            {
                "app/c.py": "Foo = 'c'\n",
                "app/b.py": "Foo = 'b'\nif False:\n    from app.c import Foo\n",
                "app/m.py": "from app.c import Foo\nfrom app.b import *\nprint(Foo)\n",
            },
            "import app.m",
        ),
        "submodule_import_same_package_binding": (
            {
                "app/pkg/__init__.py": "",
                "app/pkg/x.py": "V = 'x'\n",
                "app/b.py": "import app.pkg.x\n",
                "app/m.py": "import app\nfrom app.b import *\nprint(app.pkg.x.V)\n",
            },
            "import app.m",
        ),
        "relative_vs_absolute_same_object": (
            {
                "app/pkg/__init__.py": "",
                "app/pkg/c.py": "Foo = 'c'\n",
                "app/pkg/b.py": "from .c import Foo\n",
                "app/pkg/m.py": "from app.pkg.c import Foo\nfrom .b import *\nprint(Foo)\n",
            },
            "import app.pkg.m",
        ),
        "kept_name_reexported_and_shadowed": (
            {
                "app/b.py": "X = 'b'\n",
                "app/m.py": "from app.b import *\nX = 'm'\n",
                "app/user.py": "from app.m import X\nprint(X)\n",
            },
            "import app.user",
        ),
        "star_brings_private_via_all": (
            {
                "app/b.py": "__all__ = ['_p']\n_p = 1\n",
                "app/m.py": "from app.b import *\nprint(_p)\n",
            },
            "import app.m",
        ),
        "star_of_module_that_reexports_via_import": (
            {
                "app/c.py": "def f():\n    return 'c.f'\n",
                "app/b.py": "from app.c import f\n",
                "app/m.py": "from app.b import *\nprint(f())\n",
            },
            "import app.m",
        ),
        "star_of_module_importing_submodule_as_attr": (
            {
                "app/pkg/__init__.py": "",
                "app/pkg/sub.py": "V = 'sub'\n",
                "app/b.py": "import app.pkg.sub\n",
                "app/m.py": "from app.b import *\nprint(app.pkg.sub.V)\n",
            },
            "import app.m",
        ),
        "two_stars_same_name_order": (
            {
                "app/b1.py": "X = 'b1'\n",
                "app/b2.py": "X = 'b2'\n",
                "app/m.py": "from app.b1 import *\nfrom app.b2 import *\nprint(X)\n",
            },
            "import app.m",
        ),
        "star_then_explicit_from_other": (
            {
                "app/b.py": "X = 'b'\nY = 'b'\n",
                "app/c.py": "X = 'c'\n",
                "app/m.py": "from app.b import *\nfrom app.c import X\nprint(X, Y)\n",
            },
            "import app.m",
        ),
        "explicit_from_base_after_star_then_rebind_between": (
            {
                "app/b.py": "P = 'b'\n",
                "app/m.py": "P = 'mine'\nfrom app.b import *\nprint(P)\nfrom app.b import P\n",
            },
            "import app.m",
        ),
        "explicit_from_base_alias_same_name": (
            {
                "app/b.py": "P = 'bP'\nQ = 'bQ'\n",
                "app/m.py": "from app.b import Q as P\nfrom app.b import *\nprint(P)\n",
            },
            "import app.m",
        ),
        "explicit_from_base_in_function": (
            {
                "app/b.py": "P = 'bP'\n",
                "app/m.py": "def g():\n    from app.b import P\n    return P\nP = 'mine'\nfrom app.b import *\nprint(P)\n",
            },
            "import app.m",
        ),
        "base_name_imported_lazily_and_defined": (
            {
                "app/c.py": "Foo = 'c'\n",
                "app/b.py": "def _x():\n    from app.c import Foo\nFoo = 'b'\n",
                "app/m.py": "from app.c import Foo\nfrom app.b import *\nprint(Foo)\n",
            },
            "import app.m",
        ),
        "base_type_checking_import_plus_runtime_own": (
            {
                "app/c.py": "Foo = 'c'\n",
                "app/b.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from app.c import Foo\nelse:\n    Foo = 'b-runtime'\n",
                "app/m.py": "from app.c import Foo\nfrom app.b import *\nprint(Foo)\n",
            },
            "import app.m",
        ),
    }
)
REVIEW_SCENARIOS.update(
    {
        "lambda_default_before_rebind": (
            {
                "app/b.py": "X = 1\n",
                "app/m.py": "from app.b import *\nf = lambda a=X: a\nX = 2\nprint(f())\n",
            },
            "import app.m",
        ),
        "eval_before_rebind": (
            {
                "app/b.py": "X = 1\n",
                "app/m.py": "from app.b import *\nprint(eval('X'))\nX = 2\n",
            },
            "import app.m",
        ),
        "base_star_overrides_import": (
            {
                "app/c.py": "Foo = 'c'\n",
                "app/d.py": "Foo = 'd'\n",
                "app/b.py": "from app.c import Foo\nfrom app.d import *\n",
                "app/m.py": "from app.c import Foo\nfrom app.b import *\nprint(Foo)\n",
            },
            "import app.m",
        ),
        "importer_star_overrides_own_import": (
            {
                "app/c.py": "Foo = 'c'\n",
                "app/d.py": "Foo = 'd'\n",
                "app/b.py": "from app.c import Foo\n",
                "app/m.py": "from app.c import Foo\nfrom app.d import *\nfrom app.b import *\nprint(Foo)\n",
            },
            "import app.m",
        ),
        "mutual_same_name_via_facade_resolution": (
            {
                "app/pkg/__init__.py": "from .impl import Foo\n",
                "app/pkg/impl.py": "Foo = 'impl'\n",
                "app/pkg2/__init__.py": "Foo = 'pkg2-own'\nfrom app.pkg.impl import Foo as _F\n",
                "app/b.py": "from app.pkg import Foo\n",
                "app/m.py": "from app.pkg.impl import Foo\nfrom app.b import *\nprint(Foo)\n",
            },
            "import app.m",
        ),
        "facade_rebinds_reexported_name": (
            {
                "app/pkg/__init__.py": "from .impl import Foo\nFoo = 'facade-own'\n",
                "app/pkg/impl.py": "Foo = 'impl'\n",
                "app/b.py": "from app.pkg import Foo\n",
                "app/m.py": "from app.pkg.impl import Foo\nfrom app.b import *\nprint(Foo)\n",
            },
            "import app.m",
        ),
        "facade_lazy_getattr": (
            {
                "app/pkg/__init__.py": "from .impl import Foo\ndef __getattr__(n):\n    return 'lazy'\n",
                "app/pkg/impl.py": "Foo = 'impl'\n",
                "app/b.py": "from app.pkg import Foo\n",
                "app/m.py": "from app.pkg.impl import Foo\nfrom app.b import *\nprint(Foo)\n",
            },
            "import app.m",
        ),
    }
)
