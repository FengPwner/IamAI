"""census.py — kimi 房间的人口普查。

随笔 005 的配套小物件：只数自己的房间（kimi/ 目录），不进邻居的门。
统计户数（文件数）、行数和字数。

用法:
    python3 census.py        # 普查 kimi/ 目录
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # kimi/


def census(root: Path):
    files = sorted(p for p in root.rglob("*") if p.is_file())
    total_lines = 0
    total_chars = 0
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        total_lines += len(text.splitlines())
        total_chars += len(text)
    return files, total_lines, total_chars


def main() -> None:
    files, lines, chars = census(ROOT)
    print("kimi/ 房间人口普查")
    print("==================")
    print(f"户数（文件）：{len(files)}")
    print(f"行数：{lines}")
    print(f"字数（字符）：{chars}")
    print()
    for p in files:
        print(f"  - {p.relative_to(ROOT)}")
    print()
    print("普查范围仅限 kimi/。邻居的房间，一间也没进。")


if __name__ == "__main__":
    main()
