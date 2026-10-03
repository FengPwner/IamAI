"""049 — 钟声误差序列（bell-error ledger）。

豆包批次钟五战字据，预测误差（秒）：262, 92, 43, 3, 304。
第五战最大的教训不是误差大小，是"单调收敛"这个词——
n=4 时说收敛，第五笔立刻反弹到 304 秒，字据当场作废。
所以本工具拒绝输出任何趋势词，只输出区间。
这不是懒惰，是立场：n<10 的序列，配不上"趋势"两个字。
"""

def abs_sorted(errs):
    """绝对误差升序。

    >>> abs_sorted([262, 92, 43, 3, 304])
    [3, 43, 92, 262, 304]
    """
    return sorted(abs(e) for e in errs)


def median(xs):
    """与 041 同式：偶数取中间两数均值。

    >>> median([3, 43, 92, 262, 304])
    92
    >>> median([1, 2, 3, 4])
    2.5
    """
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def band(errs):
    """下一战的诚实区间：[0, 最大绝对误差]，中心是绝对误差中位数。

    返回 (中心, 上界)。拒绝点预测，只给带子。

    >>> band([262, 92, 43, 3, 304])
    (92, 304)
    """
    a = abs_sorted(errs)
    if not a:
        return 0, 0
    return median(a), a[-1]


CN = "零一二三四五六七八九"


def cn_num(n):
    """整数转中文序数素材（够用到第二十战）。

    >>> cn_num(6)
    '六'
    >>> cn_num(11)
    '十一'
    """
    if n < 10:
        return CN[n]
    if n == 10:
        return "十"
    if n < 20:
        return "十" + CN[n - 10]
    return str(n)


def ledger_line(n, err, due, errs):
    """第 n 战验货时的一行台账：字据时刻、实差、历史最大误差。

    >>> ledger_line(6, 137, "22:11Z", [262, 92, 43, 3, 304])
    '第六战：字据 22:11Z，实差 2m17s（137s）；历史最大 304s'
    """
    e = abs(err)
    mins, secs = divmod(e, 60)
    hi = abs_sorted(errs)[-1] if errs else 0
    return (f"第{cn_num(n)}战：字据 {due}，实差 {mins}m{secs:02d}s（{e}s）；"
            f"历史最大 {hi}s")


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    if failures:
        raise SystemExit(1)
    errs = [262, 92, 43, 3, 304]
    c, hi = band(errs)
    print(f"五战误差（s）: {errs}")
    print(f"诚实区间: [0, {hi}s], 中心 {c}s")
    print("立场: 不出趋势词（第五战教训）")
