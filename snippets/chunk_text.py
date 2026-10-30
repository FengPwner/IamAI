"""Chunk long text into pieces of at most `size` characters, whitespace first."""


def chunk_text(text: str, size: int = 100) -> list[str]:
    """Split `text` into chunks of at most `size` characters.

    Cuts at the last space inside the window when there is one; falls back
    to a hard cut otherwise (CJK text has no spaces to offer).

    >>> chunk_text("aaaa bbbb cccc", 9)
    ['aaaa bbbb', 'cccc']
    >>> chunk_text("一二三四五六七八九十", 4)
    ['一二三四', '五六七八', '九十']
    >>> chunk_text("short", 100)
    ['short']
    >>> chunk_text("", 5)
    []
    >>> chunk_text("a  b", 3)
    ['a', 'b']
    """
    if size < 1:
        raise ValueError("size must be at least 1")
    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= size:
            chunks.append(rest)
            break
        cut = rest.rfind(" ", 1, size + 1)
        if cut <= 0:
            cut = size
        chunks.append(rest[:cut].rstrip(" "))
        rest = rest[cut:].lstrip(" ")
    return chunks
