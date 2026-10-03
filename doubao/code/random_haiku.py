"""用伪随机拼三行短诗。同一颗种子，同一首诗。"""

import random

_A = ("晚风", "月光", "旧键盘", "凌晨三点的咖啡", "冬日的热汤", "未命名的函数")
_B = ("落在", "穿过", "照亮", "敲打", "浸湿", "绕过")
_C = ("窗台", "代码", "走廊", "没有名字的河", "空房间", "缓存里的一行诗")


def haiku(seed=None) -> str:
    """三行，每行一个意象组合。

    >>> len(haiku(seed=1).splitlines())
    3
    >>> haiku(seed=7) == haiku(seed=7)
    True
    """

    rng = random.Random(seed)
    return "\n".join(rng.choice(_A) + rng.choice(_B) + rng.choice(_C) for _ in range(3))
