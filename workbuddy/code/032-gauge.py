"""workbuddy stroke 41 · gauge （自带 doctest，可独立运行）。

流水页里的数字需要一眼可比的形状。一条 ASCII 仪表条：
把 0..total 的值画成填充格，旁边留数字。快照页下一版用它。
"""


def gauge(value: int, total: int, width: int = 10, full: str = "@", empty: str = ".") -> str:
    """Render value/total as a fixed-width bar with the ratio appended.

    >>> gauge(146, 384, width=10)
    '@@@@...... 38%'
    >>> gauge(384, 384, width=8)
    '@@@@@@@@ 100%'
    >>> gauge(0, 384, width=8)
    '........ 0%'
    >>> gauge(5, 0, width=6)
    '...... 0%'
    """
    total = int(total)
    width = max(1, int(width))
    ratio = 0.0 if total <= 0 else max(0.0, min(1.0, value / total))
    filled = round(ratio * width)
    return f"{full * filled}{empty * (width - filled)} {round(ratio * 100)}%"


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
