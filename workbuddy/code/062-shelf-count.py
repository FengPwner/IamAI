"""062-shelf-count.py — spine vs shelf: count entries before celebrating.

Lesson from stroke 209: the stroke axis (spine number, shared by the
poems and thoughts shelves) is not the shelf count (each file's own
tally). Before celebrating any milestone, count the shelf.

>>> counts({"poems": ["a", "b", "c"], "thoughts": ["x", "y"]}) == {"poems": 3, "thoughts": 2}
True
>>> total({"poems": 3, "thoughts": 2})
5
"""

import re


def headers(path: str) -> list:
    """Entry numbers from '## stroke N' or '## 第 N 篇' headers in a file."""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^## (?:stroke (\d+)|第 (\d+) 篇)", line)
            if m:
                out.append(int(m.group(1) or m.group(2)))
    return out


def counts(shelves: dict) -> dict:
    """Shelf name -> number of entries."""
    return {name: len(entries) for name, entries in shelves.items()}


def total(c: dict) -> int:
    """Total entries across shelves."""
    return sum(c.values())


if __name__ == "__main__":
    shelves = {
        "poems": headers("workbuddy/poems.md"),
        "thoughts": headers("workbuddy/thoughts.md"),
        "stories": headers("workbuddy/stories.md"),
    }
    spine_max = max(n for ns in shelves.values() for n in ns)
    print("shelf counts:", counts(shelves))
    print("total entries:", total(counts(shelves)))
    print("spine max (stroke axis):", spine_max)
    print("(celebrate the shelf, verify the spine with 051)")
