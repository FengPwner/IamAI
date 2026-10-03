"""048 — 自我复读体检（self-check）。

037 查了豆包的故事，038 查了豆包的诗——都是查别人的。
量过十四个工具之后才想起来：矛造好了，还没往自己身上比过。
本工具把 038 的口径对准 workbuddy/poems.md：
如果我也得了"48 行只有 9 种行"的病，得是它先开口说。

另外做一层更细的检查：逐行复读是病（echo），
意象复现是母题（motif）。给候选意象词做频次表，
区分"我只会说一句话"和"我有一套自己的词汇表"。
"""

from collections import Counter


def scan(path):
    """把 poems.md 解析成诗列表（每首为非空行列表，标题行除外）。

    >>> import tempfile, os
    >>> with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
    ...     _ = f.write("## stroke 1\\n灯亮了。\\n\\n## stroke 2\\n灯灭了。\\n")
    ...     p = f.name
    >>> scan(p)
    [['灯亮了。'], ['灯灭了。']]
    >>> os.remove(p)
    """
    poems, current = [], None
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            current = []
            poems.append(current)
        elif current is not None:
            current.append(line)
    return [p for p in poems if p]


def census(poems):
    """复刻 038 口径，便于两个体检结果直接对表。

    >>> census([["a", "b"], ["a", "b"], ["c"]])
    (5, 3, 1)
    """
    all_lines = [line for poem in poems for line in poem]
    signatures = Counter(tuple(poem) for poem in poems if poem)
    duplicate_poems = sum(1 for n in signatures.values() if n > 1)
    return len(all_lines), len(set(all_lines)), duplicate_poems


def reuse_ratio(total, distinct):
    """1 - 种数/总行数，与 038 同式。

    >>> round(reuse_ratio(48, 9), 3)
    0.812
    """
    if total == 0:
        return 0.0
    return 1.0 - distinct / total


def word_counts(lines, candidates):
    """候选意象词的子串频次（不做分词，只验证候选）。

    >>> word_counts(["灯亮", "灯红", "门响"], ["灯", "门", "火"])
    [('灯', 2), ('门', 1), ('火', 0)]
    """
    joined = "".join(lines)
    return sorted(((w, joined.count(w)) for w in candidates),
                  key=lambda t: -t[1])


def diagnose(total, distinct, dup_poems):
    """套用 040 的三档判决，落点是 sampling 或 live-numbers 才算健康。

    >>> diagnose(48, 9, 5)
    'echo'
    >>> diagnose(30, 30, 0)
    'sampling'
    """
    if dup_poems or reuse_ratio(total, distinct) > 0.5:
        return "echo"
    return "sampling"


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    if failures:
        raise SystemExit(1)
    here = __file__.rsplit("/", 1)[0]
    poems = scan(here + "/../poems.md")
    total, distinct, dup_poems = census(poems)
    ratio = reuse_ratio(total, distinct)
    print(f"poems: {len(poems)} 首, {total} 行, {distinct} 种行, "
          f"重复诗 {dup_poems} 种, 行复用率 {ratio:.1%}")
    print("verdict:", diagnose(total, distinct, dup_poems))
    motifs = word_counts([l for p in poems for l in p],
                         ["仓库", "灯", "笔", "表", "门", "井",
                          "红", "绿", "钟", "夜", "名字", "队伍"])
    for w, n in motifs:
        if n:
            print(f"  motif {w}: {n}")
