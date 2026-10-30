"""052 drift: 间隔序列的体检。

给一串批次时刻(或现成的间隔序列),报告 min/max/均值/中位数,
并判定趋势:连续同向三次以上才算加速/减速,否则一律"漂移"——
n 小的时候拒绝趋势词,是钟实验十战后立下的规矩。

>>> intervals(['00:00', '01:00', '02:30'])
[60.0, 90.0]
>>> stats([65, 60, 59, 56, 48, 72])['min']
48
>>> trend([72, 65, 60, 56])
'accelerating'
>>> trend([65, 60, 59, 56, 48, 72, 64.5, 69])
'drift'
>>> trend([48, 72])
'drift'
"""

def intervals(times):
    """'HH:MM' 时刻列 → 相邻间隔分钟列(浮点)。"""
    mins = []
    for t in times:
        h, m = t.split(":")
        mins.append(int(h) * 60 + int(m))
    out = []
    for a, b in zip(mins, mins[1:]):
        d = b - a
        if d < 0:            # 跨午夜:负差加一天
            d += 24 * 60
        out.append(float(d))
    return out


def median(xs):
    a = sorted(xs)
    n = len(a)
    if n == 0:
        return 0
    if n % 2:
        return a[n // 2]
    return (a[n // 2 - 1] + a[n // 2]) / 2


def stats(iv):
    """间隔列 → {'min','max','mean','median'}。"""
    if not iv:
        return {'min': 0, 'max': 0, 'mean': 0, 'median': 0}
    return {'min': min(iv), 'max': max(iv),
            'mean': sum(iv) / len(iv), 'median': median(iv)}


def trend(iv):
    """序列末端未被打破的同向连跑 >= 3 段才判趋势,否则漂移。

    中途的历史连跑不算数——被反转覆盖过的趋势不再作数,
    这是钟实验 48->72 的 V 型反转教会的事。

    >>> trend([72, 65, 60, 56])
    'accelerating'
    >>> trend([48, 56, 60, 66])
    'decelerating'
    >>> trend([70, 65, 60])
    'drift'
    >>> trend([48, 72])
    'drift'
    """
    if len(iv) < 4:
        return 'drift'
    d0, run = None, 0
    for a, b in zip(iv, iv[1:]):
        if b > a:
            d = 1
        elif b < a:
            d = -1
        else:
            d = 0
        if d == 0:
            d0, run = None, 0
        elif d == d0:
            run += 1
        else:
            d0, run = d, 1
    if run >= 3:
        return 'accelerating' if d0 == -1 else 'decelerating'
    return 'drift'


def verdict(iv):
    s = stats(iv)
    return "n=%d min=%.1f max=%.1f mean=%.1f median=%.1f trend=%s" % (
        len(iv), s['min'], s['max'], s['mean'], s['median'], trend(iv))


if __name__ == "__main__":
    import doctest
    assert doctest.testmod().failed == 0
    seq = [65, 60, 59, 56, 48, 72, 64.5, 69]
    print("豆包钟间隔(min):", seq)
    print(verdict(seq))
