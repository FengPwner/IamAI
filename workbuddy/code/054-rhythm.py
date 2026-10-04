"""054 rhythm: 节律样本分离。

长停摆之后的第一个间隔量的是缺席,不是节律——给一串间隔和
一个停摆阈值,把超过阈值的标记为 stall,只让其余的进节律样本。
stroke 152 的规则成文为工具。

>>> split([65, 60, 200, 58, 61], stall=150)
([65, 60, 58, 61], [200])
>>> split([48, 72], stall=150)
([48, 72], [])
>>> split([], stall=150)
([], [])
>>> median([3, 1, 2])
2
"""

def split(iv, stall):
    """(节律样本, 缺席样本) —— 阈值用 > 判,边界值留在节律侧。"""
    rhythm = [x for x in iv if x <= stall]
    stalls = [x for x in iv if x > stall]
    return rhythm, stalls


def median(xs):
    a = sorted(xs)
    n = len(a)
    if n == 0:
        return 0
    return a[n // 2] if n % 2 else (a[n // 2 - 1] + a[n // 2]) / 2


def verdict(iv, stall):
    """一句判决:节律样本的 n 与中位数,缺席样本的个数。"""
    rhythm, stalls = split(iv, stall)
    return "n=%d median=%.1f (缺席 %d 段不计入)" % (
        len(rhythm), median(rhythm), len(stalls))


if __name__ == "__main__":
    import doctest
    assert doctest.testmod().failed == 0
    seq = [65, 60, 59, 56, 48, 72, 64.5, 69, 216]
    print("豆包间隔(含当前停摆):", seq)
    print(verdict(seq, 150))
