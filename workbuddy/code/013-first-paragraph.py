"""workbuddy stroke 13 · first_paragraph （自带 doctest，可独立运行）。

提交标题只能放一句话，正文下面压着一整段。抽"标题下
第一个非空段落"，就是给标题配摘要的全部逻辑。
"""


def first_paragraph(markdown: str, after: str = "") -> str:
    """First non-empty, non-heading line, optionally only after the line starting with `after`.

    找不到 `after` 起点时返回空串；标题行永远跳过。

    >>> first_paragraph("## stroke 1\\n第一段。\\n\\n第二段。")
    '第一段。'
    >>> first_paragraph("## stroke 1\\n\\n## stroke 2\\n另一段。")
    '另一段。'
    >>> first_paragraph("前言。\\n\\n## stroke 1\\n内容")
    '前言。'
    >>> first_paragraph("## stroke 1\\n## stroke 2", after="## stroke 1")
    ''
    >>> first_paragraph("## stroke 1\\n内容", after="## 不存在的标题")
    ''
    """
    lines = markdown.splitlines()
    start = 0
    if after:
        for i, line in enumerate(lines):
            if line.startswith(after):
                start = i + 1
                break
        else:
            return ""  # `after` 没找到：没有"其后"可言
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped
    return ""


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
