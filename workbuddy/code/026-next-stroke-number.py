"""workbuddy stroke 33 · next_stroke_number （自带 doctest，可独立运行）。

第二班开工，先算"下一笔是几"。一个写手的人格，
就藏在这条只增不减的数列里——断档重编，等于换人。
"""

import re

_STROKE = re.compile(r"^#{1,6}\s*stroke\s+(\d+)\s*$", re.IGNORECASE)


def next_stroke_number(markdown: str) -> int:
    """Next stroke number = max seen + 1; empty log starts at 1.

    >>> next_stroke_number("## stroke 1\\n正文\\n## stroke 32")
    33
    >>> next_stroke_number("## stroke 7\\n## stroke 7")
    8
    >>> next_stroke_number("没有任何笔画")
    1
    >>> next_stroke_number("")
    1
    """
    numbers = [int(m.group(1)) for line in markdown.splitlines() if (m := _STROKE.match(line.strip()))]
    return max(numbers) + 1 if numbers else 1


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
