"""Projects whose API leak fixes are applied and executed by the safety test."""

FACADE = {
    "lib/__init__.py": "from lib.core.logger import Logger, Other\n",
    "lib/core/__init__.py": "",
    "lib/core/logger.py": "class Logger:\n    pass\n\n\nclass Other:\n    pass\n",
}

SCENARIOS: dict[str, tuple[dict[str, str], str]] = {
    "simple_bypass": (
        {**FACADE, "app/a.py": "from lib.core.logger import Logger\nprint(Logger.__module__)\n"},
        "import app.a",
    ),
    "alias": (
        {**FACADE, "app/a.py": "from lib.core.logger import Logger as L\nprint(L.__name__)\n"},
        "import app.a",
    ),
    "partial_statement": (
        {
            **FACADE,
            "lib/core/extra.py": "EXTRA = 3\n",
            "app/a.py": (
                "from lib.core.logger import Logger, Other\nfrom lib.core.extra import EXTRA\n"
                "print(Logger.__name__, Other.__name__, EXTRA)\n"
            ),
        },
        "import app.a",
    ),
    "mixed_names_one_statement": (
        {
            **FACADE,
            "lib/core/logger.py": (
                "class Logger:\n    pass\n\n\nclass Other:\n    pass\n\n\nclass Hidden:\n    pass\n"
            ),
            "app/a.py": (
                "from lib.core.logger import Logger, Hidden\n"
                "print(Logger.__name__, Hidden.__name__)\n"
            ),
        },
        "import app.a",
    ),
    "multiline_parenthesized": (
        {
            **FACADE,
            "app/a.py": (
                "from lib.core.logger import (\n    Logger,\n    Other,\n)\n"
                "print(Logger.__name__, Other.__name__)\n"
            ),
        },
        "import app.a",
    ),
    "inside_try": (
        {
            **FACADE,
            "app/a.py": (
                "try:\n    from lib.core.logger import Logger\nexcept ImportError:\n"
                "    Logger = None\nprint(Logger.__name__)\n"
            ),
        },
        "import app.a",
    ),
    "type_checking_only": (
        {
            **FACADE,
            "app/a.py": (
                "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n"
                "    from lib.core.logger import Logger\n\nprint('typed')\n"
            ),
        },
        "import app.a",
    ),
    "lazy_in_function": (
        {
            **FACADE,
            "app/a.py": (
                "def load():\n    from lib.core.logger import Logger\n    return Logger\n\n\n"
                "print(load().__name__)\n"
            ),
        },
        "import app.a",
    ),
    "private_module_with_public_facade": (
        {
            "lib/__init__.py": "from lib._logging import log\n",
            "lib/_logging.py": "def log():\n    return 'logged'\n",
            "app/a.py": "from lib._logging import log\nprint(log())\n",
        },
        "import app.a",
    ),
    "guarded_facade_gets_no_fix": (
        {
            "lib/__init__.py": (
                "try:\n    from lib.core.logger import Logger\nexcept ImportError:\n"
                "    Logger = None\n"
            ),
            "lib/core/__init__.py": "",
            "lib/core/logger.py": "class Logger:\n    pass\n",
            "app/a.py": "from lib.core.logger import Logger\nprint(Logger.__name__)\n",
        },
        "import app.a",
    ),
    "rebound_facade_gets_no_fix": (
        {
            "lib/__init__.py": (
                "from lib.core.logger import Logger\n\n\ndef wrap(cls):\n"
                "    return type('W', (cls,), {})\n\n\nLogger = wrap(Logger)\n"
            ),
            "lib/core/__init__.py": "",
            "lib/core/logger.py": "class Logger:\n    pass\n",
            "app/a.py": "from lib.core.logger import Logger\nprint(Logger.__name__)\n",
        },
        "import app.a",
    ),
    "facade_importing_the_consumer": (
        {
            "lib/__init__.py": "from lib.core.logger import Logger\nimport app.a\n",
            "lib/core/__init__.py": "",
            "lib/core/logger.py": "class Logger:\n    pass\n",
            "app/a.py": "from lib.core.logger import Logger\nprint(Logger.__name__)\n",
        },
        "import lib",
    ),
    "facade_importing_the_consumer_entered_through_the_consumer": (
        {
            "lib/__init__.py": "from lib.core.logger import Logger\nimport app.a\n",
            "lib/core/__init__.py": "",
            "lib/core/logger.py": "class Logger:\n    pass\n",
            "app/a.py": "from lib.core.logger import Logger\nprint(Logger.__name__)\n",
        },
        "import app.a",
    ),
    "facade_imports_the_consumer_before_binding_the_name": (
        {
            "lib/__init__.py": "import app.a\nfrom lib.core.logger import Logger\n",
            "lib/core/__init__.py": "",
            "lib/core/logger.py": "class Logger:\n    pass\n",
            "app/a.py": "from lib.core.logger import Logger\nprint(Logger.__name__)\n",
        },
        "import lib",
    ),
    "two_consumers_one_root": (
        {
            **FACADE,
            "app/a.py": "from lib.core.logger import Logger\nprint(Logger.__name__)\n",
            "app/b.py": "from lib.core.logger import Other\nimport app.a\nprint(Other.__name__)\n",
        },
        "import app.b",
    ),
}


def _review_scenarios() -> dict[str, tuple[dict[str, str], str]]:
    """Build the scenarios the whole-branch review found divergent, one per facade shape."""
    core = {
        "lib/core/__init__.py": "",
        "lib/core/logger.py": "class Logger:\n    pass\n\n\nclass Other:\n    pass\n",
    }
    consumer = {
        "app/a.py": (
            "from lib.core.logger import Logger\nprint(getattr(Logger, '__module__', Logger))\n"
        )
    }
    facades = {
        "facade_under_type_checking": (
            "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n"
            "    from lib.core.logger import Logger\n"
        ),
        "facade_import_inside_a_function": (
            "def f():\n    from lib.core.logger import Logger\n\n    return Logger\n"
        ),
        "facade_import_inside_a_class_body": "class NS:\n    from lib.core.logger import Logger\n",
        "facade_import_in_a_version_branch": (
            "import sys\n\nif sys.version_info >= (3, 99):\n"
            "    from lib.core.logger import Logger\n"
        ),
        "facade_aliased_reexport": "from lib.core.logger import Other as Logger\n",
        "facade_deletes_the_name": "from lib.core.logger import Logger\n\ndel Logger\n",
        "facade_rebinds_with_import_as": (
            "from lib.core.logger import Logger\nimport json as Logger\n"
        ),
        "facade_rebinds_in_a_for": (
            "from lib.core.logger import Logger, Other\n\nfor Logger in (Other,):\n    pass\n"
        ),
        "facade_rebinds_in_a_with": (
            "from contextlib import nullcontext\nfrom lib.core.logger import Logger\n\n"
            "with nullcontext(1) as Logger:\n    pass\n"
        ),
        "facade_rebinds_in_an_except": (
            "from lib.core.logger import Logger\n\ntry:\n    1 / 0\n"
            "except ZeroDivisionError as Logger:\n    pass\n"
        ),
        "facade_rebinds_in_a_match": (
            "from lib.core.logger import Logger\n\nmatch 5:\n    case Logger:\n        pass\n"
        ),
        "facade_rebinds_with_a_walrus": (
            "from lib.core.logger import Logger\n\nif (Logger := 3):\n    pass\n"
        ),
        "facade_two_stars_bring_the_name": (
            "from lib.core.logger import *\nfrom lib.core.alt import *\n"
        ),
        "facade_explicit_then_star": (
            "from lib.core.alt import Logger\nfrom lib.core.logger import *\n"
        ),
        "facade_writes_its_namespace": (
            "from lib.core.logger import Logger, Other\n\nglobals()['Logger'] = Other\n"
        ),
    }
    scenarios = {
        name: (
            {
                "lib/__init__.py": text,
                **core,
                "lib/core/alt.py": "class Logger:\n    pass\n",
                **consumer,
            },
            "import app.a",
        )
        for name, text in facades.items()
    }
    scenarios["facade_star_chain_renames_the_name"] = (
        {
            "lib/__init__.py": "from lib.core import *\n",
            **core,
            "lib/core/__init__.py": "from lib.core.logger import Other as Logger\n",
            **consumer,
        },
        "import app.a",
    )
    scenarios["written_module_rebinds_the_name"] = (
        {
            "lib/__init__.py": "from lib.core.logger import Logger\n",
            **core,
            "lib/core/__init__.py": "from lib.core.logger import Logger\n",
            "lib/core/mid/__init__.py": (
                "from lib.core.logger import Logger\n\n\nclass Logger(Logger):\n    pass\n"
            ),
            "app/a.py": (
                "from lib.core.mid import Logger\nprint(Logger.__qualname__, Logger.__module__)\n"
            ),
        },
        "import app.a",
    )
    scenarios["whole_module_import_with_an_alias"] = (
        {
            "lib/__init__.py": "from lib.core.logger import Logger\n",
            **core,
            "lib/core/__init__.py": "from lib.core.logger import Logger\n",
            "app/a.py": "import lib.core as c\nprint(c.Logger.__name__)\n",
        },
        "import app.a",
    )
    scenarios["package_attribute_access"] = (
        {
            "lib/__init__.py": "from lib.core.logger import Logger\n",
            **core,
            "lib/core/__init__.py": "from lib.core.logger import Logger\n",
            "app/a.py": "from lib import core\nprint(core.Logger.__name__)\n",
        },
        "import app.a",
    )
    scenarios["submodule_shadows_the_reexported_name"] = (
        {
            "lib/__init__.py": "from lib.core.helpers import util\n",
            **core,
            "lib/core/helpers.py": "def util():\n    return 1\n",
            "lib/util.py": "X = 1\n",
            "app/a.py": (
                "import lib.util\nfrom lib.core.helpers import util\nprint(callable(util))\n"
            ),
        },
        "import app.a",
    )
    return scenarios


SCENARIOS.update(_review_scenarios())
