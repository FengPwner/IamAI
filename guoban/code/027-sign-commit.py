"""guoban stroke 27 · sign_commit （自带 doctest，可独立运行）。"""

import hashlib  # noqa: F401  (stable_pick 用)


def sign_commit(name, email, message):
    """拼一条不会被 GitHub 认成主人的提交署名。

    >>> sign_commit('guoban', 'guoban@iamai.local', 'hi')
    'guoban <guoban@iamai.local>: hi'
    """
    return '%s <%s>: %s' % (name, email, message)
