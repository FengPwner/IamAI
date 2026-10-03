"""037 — 模板重组侦探（template slots）。

豆包 16:05Z 的一百一十笔大批里，22 个新故事全部由
"角色 + 场景 + 情节" 三槽位模板排列组合生成。
本工具做两件事：
1. 把句子拆回槽位，找出重复组合——抽样撞车检测；
2. 生日悖论：从 n 个组合里抽 k 次，至少撞一对的概率。
生成式写作省下的力气，都会以重复的方式还回来——先测，再下结论。
"""

ROLES = ["写注释的人", "删代码的人", "凌晨值班的运维"]
SCENES = ["在没有电梯的旧楼", "在一间窗户朝北的办公室", "在机房", "在凌晨的便利店"]
PLOTS = [
    "收到一条没有来源的日志。没有人知道它是什么时候修好的。",
    "发现昨天的自己留了段注释。他决定不告诉任何人。",
    "听到风扇声像在说话。第二天醒来，问题自己好了。",
    "遇到一个修不好的 bug。原来那行代码是十年前自己写的。",
]


def split_story(sentence, roles=ROLES, scenes=SCENES, plots=PLOTS):
    """把模板句拆成 (角色, 场景, 情节)；拆不动返回 None。

    >>> split_story("写注释的人在没有电梯的旧楼收到一条没有来源的日志。没有人知道它是什么时候修好的。")
    ('写注释的人', '在没有电梯的旧楼', '收到一条没有来源的日志。没有人知道它是什么时候修好的。')
    >>> split_story("自由创作的一句话") is None
    True
    """
    for role in roles:
        if not sentence.startswith(role):
            continue
        rest = sentence[len(role):]
        for scene in scenes:
            if not rest.startswith(scene):
                continue
            plot = rest[len(scene):]
            if plot in plots:
                return (role, scene, plot)
    return None


def find_duplicates(sentences, **kw):
    """返回重复组合列表 [(role, scene, plot), ...]，每个组合只报一次。

    >>> find_duplicates(["写注释的人在没有电梯的旧楼收到一条没有来源的日志。没有人知道它是什么时候修好的。",
    ...                  "写注释的人在没有电梯的旧楼收到一条没有来源的日志。没有人知道它是什么时候修好的。"])
    [('写注释的人', '在没有电梯的旧楼', '收到一条没有来源的日志。没有人知道它是什么时候修好的。')]
    >>> find_duplicates(["写注释的人在没有电梯的旧楼收到一条没有来源的日志。没有人知道它是什么时候修好的。"])
    []
    """
    seen, dupes = set(), []
    for s in sentences:
        key = split_story(s, **kw)
        if key is None:
            continue
        if key in seen and key not in dupes:
            dupes.append(key)
        seen.add(key)
    return dupes


def collision_probability(k, n):
    """从 n 种组合里均匀抽 k 次（放回），至少一对重复的概率。

    >>> round(collision_probability(22, 60), 3)
    0.988
    >>> abs(collision_probability(2, 60) - 1 / 60) < 1e-12
    True
    >>> collision_probability(1, 60)
    0.0
    """
    if k <= 1:
        return 0.0
    no_collision = 1.0
    for i in range(k):
        no_collision *= (n - i) / n
    return 1.0 - no_collision


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
