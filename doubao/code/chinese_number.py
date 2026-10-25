"""把阿拉伯数字念成中文，零到九千九百九十九亿九千九百九十九万九千九百九十九。"""

_DIGITS = "零一二三四五六七八九"
_UNITS = ("", "十", "百", "千")
_BIG = ("", "万", "亿", "万亿")


def _section(n: int) -> str:
    """0 <= n < 10000 转成中文（不处理“零”之外的组间规则）。"""
    if n == 0:
        return "零"
    parts: list[str] = []
    pending_zero = False
    for i in range(3, -1, -1):
        d = n // (10 ** i) % 10
        if d == 0:
            if parts:
                pending_zero = True
        else:
            if pending_zero:
                parts.append("零")
            pending_zero = False
            parts.append(_DIGITS[d] + _UNITS[i])
    return "".join(parts)


def to_chinese(n: int) -> str:
    """整数转中文数字。

    >>> to_chinese(0)
    '零'
    >>> to_chinese(12)
    '十二'
    >>> to_chinese(2026)
    '二千零二十六'
    >>> to_chinese(10000)
    '一万'
    >>> to_chinese(10001)
    '一万零一'
    >>> to_chinese(100000000)
    '一亿'
    """

    if n < 0:
        return "负" + to_chinese(-n)
    if n == 0:
        return "零"
    if n >= 10 ** 12:
        raise ValueError("超出本函数能念的范围")
    if 10 <= n < 20:
        return _section(n)[1:]

    groups: list[int] = []
    while n:
        groups.append(n % 10000)
        n //= 10000

    out: list[str] = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if not g:
            continue
        text = _section(g)
        if i < len(groups) - 1 and g < 1000 and out:
            text = "零" + text
        out.append(text + _BIG[i])
    return "".join(out)
