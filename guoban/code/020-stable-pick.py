"""guoban stroke 20 · stable_pick （自带 doctest，可独立运行）。"""

import hashlib  # noqa: F401  (stable_pick 用)


def stable_pick(items, key):
    """按 key 稳定地挑一项（同样的 key 永远挑到同一项）。

    >>> stable_pick(['a', 'b', 'c'], 'x') == stable_pick(['a', 'b', 'c'], 'x')
    True
    >>> stable_pick([], 'x') is None
    True
    """
    if not items:
        return None
    h = hashlib.sha1(str(key).encode('utf-8')).hexdigest()
    return items[int(h, 16) % len(items)]
