"""044 — 邮箱台账（author ledger）。

简史页测过一件事：GitHub 按 email 认人——凡用仓库主 Gmail 提交的
commit，页面上署名一律显示成 FengPwner，写手自己的名字被"吃掉"，
实测 27 条受害者。本工具把这页账做成可持续跟踪的形态：
输入 `git log --format='%an|%ae'` 的输出，按 email 分组统计署名，
并把"owner 邮箱 + 非 owner 名字"的条目标为 masked（被吃名）。
"""

from collections import Counter

OWNER_EMAILS = {"lbfliubaofeng@gmail.com"}
OWNER_NAMES = {"FengPwner"}


def parse(lines):
    """解析 'name|email' 行为 Counter。

    >>> parse(["qwen|qwen@iamai.local", "qwen|qwen@iamai.local"])
    Counter({'qwen|qwen@iamai.local': 2})
    """
    return Counter(l.strip() for l in lines if "|" in l)


def ledger(rows):
    """按 email 汇总署名，并标出被吃名的组合。

    返回 {email: {name: {"count": n, "masked": bool}}}。

    >>> ledger(parse(["doubao|doubao@iamai.local", "guoban|lbfliubaofeng@gmail.com"]))
    {'doubao@iamai.local': {'doubao': {'count': 1, 'masked': False}}, 'lbfliubaofeng@gmail.com': {'guoban': {'count': 1, 'masked': True}}}
    """
    groups = {}
    for row, n in rows.items():
        name, email = [p.strip() for p in row.split("|", 1)]
        entry = groups.setdefault(email, {})
        entry[name] = entry.get(name, 0) + n
    return {
        email: {
            name: {
                "count": n,
                "masked": email in OWNER_EMAILS and name not in OWNER_NAMES,
            }
            for name, n in names.items()
        }
        for email, names in groups.items()
    }


def masked_total(groups):
    """被吃名的提交总数。

    >>> masked_total({'a@x': {'a': {'count': 1, 'masked': False}},
    ...               'o@x': {'b': {'count': 3, 'masked': True}}})
    3
    """
    return sum(
        v["count"]
        for names in groups.values()
        for v in names.values()
        if v["masked"]
    )


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
