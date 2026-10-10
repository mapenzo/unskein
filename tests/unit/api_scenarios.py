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
