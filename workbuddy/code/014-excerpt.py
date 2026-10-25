"""workbuddy stroke 14 · excerpt （自带 doctest，可独立运行）。

guoban 式提交标题的最后一段是"— 摘要"。摘要规则：
不超限就原样，超限就砍到正好 limit 个字，末尾换省略号。
"""


def excerpt(text: str, limit: int = 16) -> str:
    """Trim `text` to at most `limit` characters, ellipsis marking the cut.

    >>> excerpt("短句")
    '短句'
    >>> excerpt("一二三四五六七八九十", limit=8)
    '一二三四五六七…'
    >>> excerpt("正好十六个字正好十六个字正好十六字", limit=16)
    '正好十六个字正好十六个字正好十…'
    >>> len(excerpt("很长很长很长很长很长很长", limit=10))
    10
    """
    if len(text) <= int(limit):
        return text
    return text[: int(limit) - 1] + "…"


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
