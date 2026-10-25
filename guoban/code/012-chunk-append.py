"""guoban stroke 12 · chunk_append （自带 doctest，可独立运行）。"""

import hashlib  # noqa: F401  (stable_pick 用)


def chunk_append(old, line, limit=200):
    """把一行追加到文本末尾，超过 limit 行就丢掉最老的几行。

    >>> chunk_append('a\nb', 'c')
    'a\nb\nc'
    >>> chunk_append('1\n2\n3', '4', limit=2)
    '3\n4'
    """
    lines = [l for l in (old or '').splitlines() if l != '']
    lines.append(line)
    if limit is not None and len(lines) > limit:
        lines = lines[-limit:]
    return '\n'.join(lines)
