"""039 — 笔记解剖（note anatomy）。

豆包批次的三种文体体检完：故事是纯组合（1 对重复），
诗是纯组合（5 对重复），笔记却是另一种生物——
四槽位骨架（引子 / 主题句 / 此刻 / 结尾）里嵌着活数字：
提交数和行数是写笔时实测的，所以笔记永远不会整条重复。
本工具把一条 dnote 拆回四段，并把数字归一化后查重复——
归一化后还相同，才是真复读；数字不同，骨架复用也算它诚实。
"""

import re

NUM = re.compile(r"\d+")


def split_note(text):
    """把一条 dnote 拆成 (intro, thesis, now, outro)。

    结构：`第 N 笔：` 开头的引子一行；主题句；`此刻：` 开头的现状；
    结尾一句。拆不动返回 None。

    >>> split_note("第 355 笔：doubao/code/palindrome_chinese.py 已经在代码池里了，这一笔改记随笔。名字是代码的第一次面试，面试不过，后面全是将就。 此刻：豆包已写下 149 笔中的一部分，总数在涨。 以上内容不需要立刻有用，先占个位置。")
    ('第 355 笔：doubao/code/palindrome_chinese.py 已经在代码池里了，这一笔改记随笔。', '名字是代码的第一次面试，面试不过，后面全是将就。', '此刻：豆包已写下 149 笔中的一部分，总数在涨。', '以上内容不需要立刻有用，先占个位置。')
    >>> split_note("自由的一句话")
    """
    m = re.match(r"^(第 \d+ 笔：[^。]*。)(.*?)( 此刻：.*?。)(.*)$", text)
    if not m:
        return None
    intro, thesis, now, outro = m.groups()
    return (intro, thesis.strip(), now.strip(), outro.strip())


def skeleton(text):
    """数字归一化后的骨架签名：活数字换成 #，骨架复用一目了然。

    >>> skeleton("此刻：121 个文件在生长，108 次提交证明它没停过。")
    '此刻：# 个文件在生长，# 次提交证明它没停过。'
    >>> skeleton("规则少到一条，才配叫规则：每十分钟提交一次。")
    '规则少到一条，才配叫规则：每十分钟提交一次。'
    """
    return NUM.sub("#", text)


def true_duplicates(notes):
    """整条笔记归一化后仍相同的条数（真复读）。

    注意：数字不同但骨架相同也算——骨架复读正是本工具要抓的。

    >>> true_duplicates(["此刻：121 个文件，108 次提交。", "此刻：124 个文件，111 次提交。"])
    1
    >>> true_duplicates(["此刻：121 个。", "写到这里，夜和光标一样亮。"])
    0
    >>> true_duplicates(["规则少到一条。", "规则少到一条。", "规则少到一条。"])
    1
    """
    seen = {}
    for n in notes:
        sig = skeleton(n)
        seen[sig] = seen.get(sig, 0) + 1
    return sum(1 for v in seen.values() if v > 1)


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
