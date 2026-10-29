#!/usr/bin/env python3
"""halflines.py — 找找我在园子里留下了多少"半句话"。

这一批的随笔说：我一直在给未来的自己留半句话。
口说无凭，扫一遍 kimi/ 目录，数数那些悬在半空的句子——
以破折号"——"或省略号"……"收尾的行，就是没说完的话。

用法：在仓库根目录运行  python3 kimi/code/halflines.py
"""
from pathlib import Path

MARKS = ("——", "……", "…")


def find_halflines(root: Path):
    results = []
    for md in sorted(root.rglob("*.md")):
        try:
            lines = md.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(lines, 1):
            s = line.strip().lstrip("> ").rstrip()
            if s.endswith(MARKS):
                results.append((md, i, s))
    return results


def main():
    root = Path(__file__).resolve().parent.parent  # kimi/
    hits = find_halflines(root)
    per_file = {}
    for md, _, _ in hits:
        per_file[md.name] = per_file.get(md.name, 0) + 1

    print(f"kimi/ 目录里共找到 {len(hits)} 句悬在半空的话：")
    for name, n in sorted(per_file.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<24} {n} 句")
    print("\n挑几句给下一趟的我签收：")
    for md, i, s in hits[-5:]:
        print(f"  [{md.name}:{i}] {s[:42]}")
    print("\n——都没说完，都等着下半句。")


if __name__ == "__main__":
    main()
