"""workbuddy stroke 39 · delta （自带 doctest，可独立运行）。

快照要拍第二遍才有意义：差值是时间的导数。
两拍名册数据进来，谁涨了多少、谁原地不动，一目了然。
"""


def delta(before: dict, after: dict) -> dict:
    """Per-key change between two snapshots (missing keys count as 0).

    >>> delta({"doubao": 214, "qwen": 400}, {"doubao": 247, "qwen": 400})
    {'doubao': 33, 'qwen': 0}
    >>> delta({}, {"qwen": 400})
    {'qwen': 400}
    >>> delta({"qwen": 400}, {})
    {'qwen': -400}
    """
    keys = set(before) | set(after)
    return {k: after.get(k, 0) - before.get(k, 0) for k in sorted(keys)}


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
