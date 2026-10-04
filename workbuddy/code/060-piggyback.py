"""060-piggyback-check.py — did the content ride an envelope?

Night lesson, twice verified by hand: a window can land
"Everything up-to-date" and still have delivered — its content rode a
previous window's per-attempt envelope (056's fission; the law
"land early beats batch late"). The commit message is a postmark,
not a manifest. This tool turns the manual check (grep the tip)
into a function: verify the marker is present in the file at a rev
before claiming the window delivered it.

>>> rode_envelope("第 23 篇《插头》", "## 第 22 篇《客房》\\n## 第 23 篇《插头》")
True
>>> rode_envelope("第 24 篇", "## 第 23 篇《插头》")
False
>>> rode_envelope("", "anything at all")
True
"""

import subprocess


def rode_envelope(marker: str, file_text: str) -> bool:
    """True if the marker is already present in the file text.

    Empty marker counts as present (nothing to wait for).
    """
    return marker in file_text


def show(rev: str, path: str) -> str:
    """File content at a rev, via git show.

    >>> isinstance(show("HEAD", "workbuddy/poems.md"), str)
    True
    """
    out = subprocess.run(
        ["git", "show", f"{rev}:{path}"],
        capture_output=True,
        text=True,
    )
    return out.stdout


if __name__ == "__main__":
    text = show("origin/main", "workbuddy/stories.md")
    print("story 23 on remote:", rode_envelope("第 23 篇《插头》", text))
    print("story 24 on remote:", rode_envelope("第 24 篇", text))
    poems = show("origin/main", "workbuddy/poems.md")
    print("poem 197 on remote:", rode_envelope("《预算》", poems))
