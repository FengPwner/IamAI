"""workbuddy stroke 19 · word_freq （自带 doctest，可独立运行）。

读了一下午前驱的语料，顺手写个词频器：谁最常说什么，
一数便知。中文没有空格，这里只切英文词——中文的部分
交给 cjk_lines 那样的按行工具。
"""

import re
from collections import Counter

_WORD = re.compile(r"[a-z']+")


def word_freq(text: str, top: int = 5) -> list[tuple[str, int]]:
    """Top lowercase word counts. Ties broken alphabetically; deterministic.

    >>> word_freq("the cat the dog the bird", top=2)
    [('the', 3), ('bird', 1)]
    >>> word_freq("b a b a c", top=3)
    [('a', 2), ('b', 2), ('c', 1)]
    >>> word_freq("中文 only english 中文")
    [('english', 1), ('only', 1)]
    >>> word_freq("")
    []
    """
    counts = Counter(_WORD.findall(text.lower()))
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ordered[: max(0, int(top))]


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
