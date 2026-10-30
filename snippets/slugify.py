"""Turn a title into a URL-ish slug without unicode surgery."""

import re

_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str, sep: str = "-") -> str:
    """Lowercase, transliterate nothing, collapse junk into one separator.

    >>> slugify("  Hello,   World! ")
    'hello-world'
    >>> slugify("IamAI -- round 12", "_")
    'iamai_round_12'
    >>> slugify("###")
    ''
    """

    return _STRIP.sub(sep, str(text).lower()).strip(sep)
