"""workbuddy stroke 21 · merge_sorted （自带 doctest，可独立运行）。

两个写手各有一列有序的笔号，对账时要把它们并成一列有序。
并集去重（同一笔不该数两遍），稳定保持相对顺序。
"""


def merge_sorted(a, b):
    """Merge two sorted lists of stroke numbers, keeping one copy of each.

    >>> merge_sorted([1, 3, 5], [2, 3, 4])
    [1, 2, 3, 4, 5]
    >>> merge_sorted([], [7, 8])
    [7, 8]
    >>> merge_sorted([1, 1, 2], [2])
    [1, 2]
    """
    out = []
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] < b[j]:
            val, i = a[i], i + 1
        else:
            val, j = b[j], j + 1
        if not out or out[-1] != val:
            out.append(val)
    tail = a[i:] or b[j:]
    for val in tail:
        if not out or out[-1] != val:
            out.append(val)
    return out


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
