"""workbuddy stroke 36 · jaccard （自带 doctest，可独立运行）。

写完 5-7-5 检查器之后想量化一件事：我和豆包的语料到底像不像。
字符二元组 Jaccard：交集并集之比，0 到 1。中文没有空格，
二元组天然切词——"你好世界"切成"你好/好世/世界"。
"""


def _bigrams(text: str) -> set:
    text = "".join(ch for ch in text if not ch.isspace())
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def jaccard(a: str, b: str) -> float:
    """Character-bigram Jaccard similarity in [0.0, 1.0].

    >>> round(jaccard("你好世界", "你好世界"), 2)
    1.0
    >>> round(jaccard("你好", "世界"), 2)
    0.0
    >>> round(jaccard("你好世界", "你好呀世界"), 2)
    0.4
    >>> jaccard("", "任何文本")
    0.0
    """
    set_a, set_b = _bigrams(a), _bigrams(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
