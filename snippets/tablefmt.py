"""Render rows as an aligned text table -- no pandas required to read a log."""


def render_table(headers, rows, gap: int = 2) -> str:
    """Return a plain-text table, columns widened to their content.

    >>> print(render_table(["a", "bb"], [[1, 2], [100, 20]]), end="")
      a bb
    --- --
      1  2
    100 20
    """

    cols = [str(h) for h in headers]
    widths = [len(c) for c in cols]
    text_rows = []
    for row in rows:
        cells = [str(cell) for cell in row]
        for i, cell in enumerate(cells[: len(widths)]):
            widths[i] = max(widths[i], len(cell))
        text_rows.append(cells)

    def line(cells):
        return " ".join(str(c).rjust(widths[i]) for i, c in enumerate(cells)) + "\n"

    rule = ["-" * w for w in widths]
    out = [line(cols), line(rule)]
    out += [line(r) for r in text_rows]
    return "".join(out)
