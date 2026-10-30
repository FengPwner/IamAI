"""workbuddy stroke 12 · stroke_numbers （自带 doctest，可独立运行）。

每个写手的 md 都是 "## stroke N" 的长卷。把它变成一列整数，
就能对账：写到第几笔、跳没跳号、断没断档。
"""

import re

_STROKE = re.compile(r"^#{1,6}\s*stroke\s+(\d+)\s*$", re.IGNORECASE)


def stroke_numbers(markdown: str) -> list[int]:
    """Stroke numbers in file order. Duplicates kept — 对账要的是原貌。

    >>> stroke_numbers("## stroke 1\\n内容\\n## stroke 2\\n# Stroke 3")
    [1, 2, 3]
    >>> stroke_numbers("## stroke 7\\n## stroke 7")
    [7, 7]
    >>> stroke_numbers("## 其他标题\\n正文")
    []
    """
    return [int(m.group(1)) for line in markdown.splitlines() if (m := _STROKE.match(line.strip()))]


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
