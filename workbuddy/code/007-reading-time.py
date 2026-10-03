"""workbuddy stroke 7 · reading_time （自带 doctest，可独立运行）。

一个全是字的仓库，值得一个估阅读时长的小工具。
中文按每分钟 300 字，英文按每分钟 200 词，混排就都算一遍取和。
"""

import math
import re

_WORD = re.compile(r"[A-Za-z0-9']+")


def reading_time(text: str) -> int:
    """Estimated reading minutes, rounded up, minimum 1 for non-empty text.

    >>> reading_time("")
    0
    >>> reading_time("短文一篇")
    1
    >>> reading_time("字" * 600)
    2
    >>> reading_time("one two three four")
    1
    >>> reading_time("word " * 400 + "字" * 300)
    3
    """
    cjk = sum(1 for ch in text if "一" <= ch <= "𰀀")
    words = len(_WORD.findall(text))
    minutes = cjk / 300 + words / 200
    if minutes <= 0:
        return 0
    return max(1, math.ceil(minutes))


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
