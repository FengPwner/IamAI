"""051 stroke-registry: 查初见,对全轴。

poems/thoughts/stories 三个文件共用一条 stroke 编号轴(早期 1-43 为双轴遗留,
各文件独立计数;后来 poems 改用共享轴的空位)。本工具扫描 '## stroke N' 标题,
报告占用、撞号与空缺,供每次新增 stroke 前自查——先查有没有,再宣布第一次。

>>> r = scan({'t': '## stroke 1\\n\\n## stroke 3\\n', 'p': '## stroke 2\\n'})
>>> r == {'t': [1, 3], 'p': [2]}
True
>>> duplicates({'t': [1, 2], 'p': [2, 3]})
{2: ['p', 't']}
>>> gaps([1, 2, 4])
[3]
>>> gaps([5, 3, 1, 1])
[2, 4]
"""

import re

_HEAD = re.compile(r"^##\s+stroke\s+(\d+)", re.M)


def scan(files):
    """从 {文件名: 内容} 提取每文件的 stroke 号(升序去重)。"""
    return {name: sorted(set(int(n) for n in _HEAD.findall(text)))
            for name, text in files.items()}


def duplicates(alloc):
    """返回 {号: [文件名...]},只含出现于多于一个文件的号。"""
    seen = {}
    for name, nums in alloc.items():
        for n in nums:
            seen.setdefault(n, []).append(name)
    return {n: sorted(names) for n, names in seen.items() if len(names) > 1}


def gaps(nums):
    """升序号列中缺失的号(去重后按区间端点找洞)。"""
    uniq = sorted(set(nums))
    if len(uniq) < 2:
        return []
    holes = []
    for lo, hi in zip(uniq, uniq[1:]):
        holes.extend(range(lo + 1, hi))
    return holes


def verdict(alloc):
    """一句话体检:撞号数与空缺数。"""
    dup = duplicates(alloc)
    all_nums = [n for nums in alloc.values() for n in nums]
    miss = gaps(all_nums)
    return "撞号 %d 处 %s;空缺 %d 个(双轴遗留另计)" % (
        len(dup), dup or "无", len(miss))


if __name__ == "__main__":
    import doctest
    import json
    assert doctest.testmod().failed == 0
    names = ["workbuddy/thoughts.md", "workbuddy/poems.md", "workbuddy/stories.md"]
    files = {n: open(n).read() for n in names}
    alloc = scan(files)
    for n in names:
        print(n, "→", alloc[n][-8:])
    print(json.dumps(duplicates(alloc), ensure_ascii=False))
    print("轴最大:", max(v[-1] for v in alloc.values() if v))
    print(verdict(alloc))
