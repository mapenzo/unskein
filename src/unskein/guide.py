"""Usage guide shipped with the package, in every supported language."""

from unskein import __version__
from unskein.i18n import Lang
from unskein.resources import read_package_text

VERSION_PLACEHOLDER = "{version}"


def usage_guide(lang: Lang) -> str:
    """Return the Markdown usage guide of the installed version.

    Args:
        lang: Language of the guide.

    Returns:
        The guide, with the installed version in its title.
    """
    guide = read_package_text(f"guides/guide.{lang}.md")
    return guide.replace(VERSION_PLACEHOLDER, __version__)
