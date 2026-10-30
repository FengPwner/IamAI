"""Parse `key=value` config lines, tolerating comments and quotes."""

QUOTES = ('"', "'")


def parse_kv(text: str) -> dict:
    r"""Turn lines of `k=v` into a dict. Later keys win.

    >>> parse_kv("a=1\n# comment\n b = two\nbad line\n")
    {'a': '1', 'b': 'two'}
    >>> parse_kv('x="quoted value"')
    {'x': 'quoted value'}
    """

    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in QUOTES:
            value = value[1:-1]
        out[key.strip()] = value
    return out
