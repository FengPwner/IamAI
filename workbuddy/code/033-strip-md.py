"""workbuddy stroke 42 · strip_md （自带 doctest，可独立运行）。

统计故事和笔记的正文之前，得先把 markdown 的行内标记剥掉：
**粗体**、*斜体*、`代码`、[链接](地址)。剥干净了，词频才不撒谎。
"""

import re

_MARKS = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`|\[(.+?)\]\((.+?)\)")


def strip_md(text: str) -> str:
    """Remove inline markdown emphasis, code and link syntax.

    >>> strip_md("**粗体** 和 *斜体*")
    '粗体 和 斜体'
    >>> strip_md("看 `pool.py` 与 [仓库](https://x.y)")
    '看 pool.py 与 仓库'
    >>> strip_md("普通一句话")
    '普通一句话'
    >>> strip_md("")
    ''
    """
    def repl(m):
        return m.group(1) or m.group(2) or m.group(3) or m.group(4) or ""

    return _MARKS.sub(repl, text)


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
