"""一帧 ASCII 雨。同一帧号，同一场雨。"""

import random


def rain(frame: int = 0, width: int = 24, height: int = 8, seed: int = 7) -> str:
    """按帧号生成一帧雨幕。

    >>> rain(0) == rain(0)
    True
    >>> len(rain(0, width=8, height=4).splitlines())
    4
    """

    rng = random.Random(seed + frame)
    drops = [(rng.randrange(width), rng.randrange(height)) for _ in range(width * 2)]
    grid = [[" "] * width for _ in range(height)]
    for x, y in drops:
        grid[y][x] = "|"
    return "\n".join("".join(row) for row in grid)
