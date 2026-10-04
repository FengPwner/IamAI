"""guoban stroke 20 · read_token （便携版自带 doctest）。"""

def read_token(env=(), files=()):
    """按序取第一个非空的令牌；都没有就返回 None。

    >>> read_token(env={'GUOBAN_TOKEN': 'abc'})
    'abc'
    >>> read_token() is None
    True
    """
    for k in env:
        v = env.get(k, '').strip()
        if v:
            return v
    return None
