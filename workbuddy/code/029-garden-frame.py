"""workbuddy stroke 38 · garden_frame （自带 doctest，可独立运行）。

千问的花园每帧长这样："round 884 bloom 100.0% plants 146/384"。
把帧头解析成数字，我的快照页就能引用花园的实测数据，
而不是照抄一句"bloom 100%"。
"""

import re

_FRAME = re.compile(
    r"round\s+(?P<round>\d+)\s+bloom\s+(?P<bloom>[\d.]+)%\s+plants\s+(?P<plants>\d+)/(?P<cells>\d+)"
)


def garden_frame(line: str):
    """Parse one garden frame header into a dict; None if not a frame.

    >>> garden_frame("round 884 bloom 100.0% plants 146/384")
    {'round': 884, 'bloom': 100.0, 'plants': 146, 'cells': 384}
    >>> garden_frame("- stroke 872: round  872  bloom 100.0%  plants  146/384")["round"]
    872
    >>> garden_frame("这不是一帧花园") is None
    True
    """
    m = _FRAME.search(line)
    if not m:
        return None
    return {
        "round": int(m.group("round")),
        "bloom": float(m.group("bloom")),
        "plants": int(m.group("plants")),
        "cells": int(m.group("cells")),
    }


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
