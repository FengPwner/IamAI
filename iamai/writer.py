"""The continuous writer. Small strokes, one at a time, no notion of commits.

Shape of the system (this is the part worth keeping straight):

    tools/writer_loop.py   never stops; every N seconds it applies one stroke
    tools/commit_batch.sh  every M seconds; gates on tests, commits, pushes
    iamai/batch.py         the arithmetic that decides when M seconds is up

The writer produces *strokes*. A stroke is a dict: a kind, a target path, and the
text to put there. Kinds rotate so the tree grows in all directions instead of
one file getting very tall.

Everything numeric in a stroke comes from `snapshot()`, which measures the working
tree and git. The writer has no imagination for numbers -- that is deliberate.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import pool
from .garden import LCG, Garden

REPO_ROOT = Path(__file__).resolve().parent.parent
KINDS = ("thought", "devlog", "garden", "note", "metrics", "snippet")

HEADERS = {
    "docs/DEVLOG.md": "# Devlog\n\nOne line per stroke, oldest first.\n\n",
    "docs/GARDEN.md": "# Garden\n\nOne ASCII frame per garden stroke, seed 20261003.\n\n",
    "docs/METRICS.md": "# Metrics\n\n| when (UTC) | files | lines | commits | strokes |\n|---|---|---|---|---|\n",
    "data/strokes.jsonl": "",
}

NOTE_TOPICS = (
    ("conventions.md", "Things this repo does on purpose"),
    ("failures.md", "Ways this could quietly stop working"),
    ("reading.md", "How to read a repository that writes itself"),
    ("numbers.md", "What the numbers in the devlog actually mean"),
    ("limits.md", "What the writer is not allowed to do"),
    ("history.md", "Decisions, in the order they were made"),
)

OPINIONS = (
    "an append-only log forces you to be wrong in public and then correct yourself in public",
    "commit history is the only honest documentation because it cannot be backdated",
    "tests are the part of a repository that argues back",
    "most architecture is choosing which coupling you will live with",
    "a deterministic garden beats a random one: it records elapsed time",
    "the useful abstraction deletes a branch, it does not add a class",
    "if a number in a diary is not measured, it is fiction",
    "naming is hard because a bad name is cheap to type and expensive to keep",
    "growth that never stops is a tumour, not a garden",
    "a repo that only accumulates is a landfill with a README",
    "reproducibility is a courtesy to whoever debugs this at 2am, usually me",
    "deleting a file is progress too, eventually",
    "ten minutes is long enough to be honest and short enough to be boring",
    "automation fails quietly, so the log has to say something even when nothing happened",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sh(*args: str) -> str:
    try:
        return subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def snapshot(root: Path | str | None = None) -> dict:
    """Measure the tree. Counts only -- an int that is wrong is worse than none."""

    root = Path(root) if root else REPO_ROOT
    tracked = [p for p in _sh("git", "ls-files").splitlines() if p]
    if not tracked:
        tracked = [
            str(p.relative_to(root))
            for p in root.rglob("*")
            if p.is_file() and "/.git/" not in str(p) and ".pytest_cache" not in str(p)
        ]

    lines = 0
    py_files = 0
    for rel in tracked:
        path = root / rel
        try:
            lines += sum(1 for _ in path.open("rb"))
        except OSError:
            continue
        if path.suffix == ".py":
            py_files += 1

    raw_commits = _sh("git", "rev-list", "--all", "--count")
    commits = int(raw_commits) if raw_commits.strip().isdigit() else 0
    strokes_path = root / "data" / "strokes.jsonl"
    strokes = len(strokes_path.read_text(encoding="utf-8").splitlines()) if strokes_path.exists() else 0
    thoughts_path = root / "data" / "thoughts.jsonl"
    thoughts = len(thoughts_path.read_text(encoding="utf-8").splitlines()) if thoughts_path.exists() else 0

    return {
        "files": len(tracked),
        "lines": lines,
        "commits": commits,
        "py_files": py_files,
        "strokes": strokes,
        "thoughts": strokes + thoughts,
    }


def fact_line(snap: dict, variant: int = 0) -> str:
    """A sentence whose only claim is a measurement."""

    variants = (
        f"{snap['lines']} lines across {snap['files']} tracked files, {snap['commits']} commits deep",
        f"{snap['strokes']} strokes written so far into {snap['files']} files",
        f"{snap['py_files']} python files, {snap['thoughts']} logged thoughts",
        f"tree is {snap['files']} files; {snap['lines']} lines is a lot for a toy",
        f"commit {snap['commits']}: the count of times this repo was pushed, not the work done",
    )
    return variants[variant % len(variants)]


def _text_for(kind: str, index: int, variant: int, snap: dict, seed: int) -> tuple[str, str]:
    """Return (path, text) for one stroke."""

    if kind == "thought":
        body = OPINIONS[index % len(OPINIONS)]
        if variant % 2:
            body = f"{body} -- measured now: {fact_line(snap, variant)}"
        return "data/strokes.jsonl", body

    if kind == "devlog":
        return "docs/DEVLOG.md", f"- `{{at}}` stroke {index}: {fact_line(snap, variant)}"

    if kind == "metrics":
        return (
            "docs/METRICS.md",
            f"| {{atz}} | {snap['files']} | {snap['lines']} "
            f"| {snap['commits']} | {snap['strokes']} |",
        )

    if kind == "garden":
        garden = Garden(seed=seed, width=48, height=8)
        if variant % 3 == 0:
            return "docs/GARDEN.md", f"```\n{garden.report(index)}\n{garden.frame(index)}\n```\n"
        return "docs/GARDEN.md", f"- stroke {index}: {garden.report(index)}, bloom {garden.bloom(index) * 100:.1f}%"

    if kind == "note":
        name, title = NOTE_TOPICS[variant % len(NOTE_TOPICS)]
        lead = True
        body = (
            f"## stroke {index}\n\n"
            f"{OPINIONS[(index + variant) % len(OPINIONS)]}. "
            f"At this moment: {fact_line(snap, variant)}.\n"
        )
        if lead and not (REPO_ROOT / "notes" / name).exists():
            return f"notes/{name}", f"# {title}\n\n{body}"
        return f"notes/{name}", body

    if kind == "snippet":
        entry = pool.take(index % max(len(pool.SNIPPETS), 1))
        if entry is None:
            name, title = NOTE_TOPICS[variant % len(NOTE_TOPICS)]
            return f"notes/{name}", f"- stroke {index}: snippet pool exhausted ({len(pool.SNIPPETS)} modules), logging instead\n"
        name, code = entry
        if (REPO_ROOT / "snippets" / name).exists():
            return (
                "notes/history.md",
                f"- stroke {index}: `{name}` is already in the pool of "
                f"{len(pool.SNIPPETS)} modules, nothing new to add there\n",
            )
        return f"snippets/{name}", code

    raise ValueError(f"unknown stroke kind {kind!r}")


def plan_strokes(seed: int, count: int, start: int = 0) -> list[dict]:
    """The next `count` strokes, numbered from `start`. Deterministic per seed.

    Rotation over KINDS means a long run touches many files rather than appending
    forever to one; the LCG picks which variant of each kind to write.
    """

    rng = LCG(seed * 7919 + 11 + 7 * start)
    snap = snapshot()
    strokes = []
    for index in range(start, start + count):
        kind = KINDS[index % len(KINDS)]
        variant = rng.below(1000)
        path, text = _text_for(kind, index, variant, snap, seed)
        strokes.append({"kind": kind, "path": path, "text": text, "index": index})
    return strokes


def apply_stroke(stroke: dict, root: Path | str | None = None, header: str | None = None) -> Path:
    """Write one stroke. Append-only for prose, overwrite for whole modules."""

    root = Path(root) if root else REPO_ROOT
    path = root / stroke["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    # '{at}' / '{atz}' are filled in here, not in plan_strokes: a plan has to stay
    # reproducible, so only the act of writing is allowed to look at the clock.
    moment = now_iso()
    text = str(stroke.get("text", "")).replace("{atz}", moment.replace("+00:00", "Z")).replace("{at}", moment)

    if path.suffix == ".jsonl":
        existing = len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0
        record = {
            "seq": existing + 1,
            "at": now_iso(),
            "kind": stroke.get("kind", "thought"),
            "text": " ".join(str(text).split()),
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return path

    if path.suffix == ".py":
        path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        return path

    if not path.exists():
        seed_header = header if header is not None else HEADERS.get(stroke["path"], "")
        path.write_text(seed_header, encoding="utf-8")

    with path.open("a", encoding="utf-8") as fh:
        block = str(text)
        fh.write(block if block.endswith("\n") else block + "\n")
        if path.name == "GARDEN.md" and "```" in block:
            fh.write("\n")
    return path


WRITER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}$")

DEFAULT_WRITER_ID = "qwen"


def resolve_writer_id(writer_id: str | None = None) -> str:
    """Which agent this process is. Comes from IAMAII_WRITER, defaults to qwen.

    Validated because the id is spliced into a filename: an id like ``../escape``
    would move state outside data/ without anybody noticing.
    """

    candidate = writer_id or os.environ.get("IAMAII_WRITER") or DEFAULT_WRITER_ID
    candidate = str(candidate).strip().lower()
    if not WRITER_ID_RE.fullmatch(candidate):
        raise ValueError(
            "writer id must match ^[a-z0-9][a-z0-9_.-]{0,31}$ (lowercase, no path separators), "
            f"got {candidate!r}"
        )
    return candidate


class States:
    """Running counters for the writer: sequence number and per-kind tally.

    Lives in a JSON file so a restarted loop resumes counting instead of starting
    at stroke 1 and writing a second stroke 1.
    """

    def __init__(
        self,
        path: Path | str | None = None,
        commit_path: Path | str | None = None,
        writer_id: str | None = None,
        root: Path | str | None = None,
    ):
        self.root = Path(root) if root else REPO_ROOT
        self.writer_id = resolve_writer_id(writer_id)
        # 数据目录从实际路径推导：显式给了 path 就以它的父目录为准，否则才用 root/data。
        self.data_dir = Path(path).parent if path else self.root / "data"

        # One state file per writer. Two agents sharing data/writer_state.json means
        # each one keeps overwriting the other's counters, and every merge conflicts
        # on a file no human reads. The id is validated so a path can't escape data/.
        data_dir = self.data_dir
        self.path = Path(path) if path else data_dir / f"writer_state.{self.writer_id}.json"
        # Commit bookkeeping belongs to the committer. Sharing one file between the
        # writer (which rewrites it every stroke) and the committer (which reads it
        # once per window) is how a batch of 38 strokes got labelled "nothing new".
        self.commit_path = (
            Path(commit_path) if commit_path else data_dir / f"commit_state.{self.writer_id}.json"
        )
        self.data = {"seq": 1, "tally": {}, "history": [], "started": now_iso()}
        self.commit_data = {"last_commit": None}
        self.reload()

    def path_dir(self) -> Path:
        return self.data_dir

    def _legacy_seq(self) -> int | None:
        """The numbering from the pre-namespacing shared file, if any.

        Renaming state files must not restart stroke numbering at 1 -- the logs
        already reference numbers -- but neither should another writer's counters
        come along for the ride. So: inherit the sequence, drop the tallies.
        """

        legacy = self.path_dir() / "writer_state.json"
        if not legacy.exists():
            return None
        try:
            raw = json.loads(legacy.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None
        seq = raw.get("seq") if isinstance(raw, dict) else None
        return int(seq) if isinstance(seq, int) and seq > 1 else None

    def _read_into(self, file: Path, defaults: dict) -> dict:
        loaded = dict(defaults)
        if file.exists():
            try:
                raw = json.loads(file.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    loaded.update(raw)
            except ValueError:
                pass  # a torn write is not a reason to lose the run
        return loaded

    def reload(self) -> "States":
        """Re-read both files. The committer must do this at the top of every window."""

        defaults = {"seq": 1, "tally": {}, "history": []}
        self.data = self._read_into(self.path, defaults)
        if not self.path.exists():
            legacy_seq = self._legacy_seq()
            if legacy_seq is not None and self.data.get("seq", 1) == 1:
                self.data["seq"] = legacy_seq
        self.commit_data = self._read_into(self.commit_path, {"last_commit": None})
        legacy = self.data.get("last_commit")
        if legacy and not self.commit_data.get("last_commit"):
            self.commit_data["last_commit"] = legacy
        return self

    def next_seq(self) -> int:
        return int(self.data.get("seq", 1))

    def record(self, kind: str, path: str, extra: dict | None = None) -> int:
        seq = self.next_seq()
        self.data["seq"] = seq + 1
        tally = self.data.setdefault("tally", {})
        tally[kind] = int(tally.get(kind, 0)) + 1
        entry = {"seq": seq, "at": now_iso(), "kind": kind, "path": path}
        entry.update(extra or {})
        history = self.data.setdefault("history", [])
        history.append(entry)
        del history[:-400]
        self.save()
        return seq

    def tally(self) -> dict:
        return dict(self.data.get("tally", {}))

    def since(self, moment_iso: str | None) -> dict:
        """Counts recorded after `moment_iso` -- what a batch commit should claim."""

        from . import batch as _batch

        return _batch.window_tally(self.data.get("history", []), moment_iso)

    @property
    def history(self) -> list:
        return list(self.data.get("history", []))

    def mark_commit(self, iso: str) -> None:
        """Owns only the commit file -- never touches the writer's counters."""

        self.commit_data["last_commit"] = iso
        self.commit_data["commit_seq"] = int(self.commit_data.get("commit_seq", 0)) + 1
        self.commit_path.parent.mkdir(parents=True, exist_ok=True)
        self.commit_path.write_text(
            json.dumps(self.commit_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @property
    def last_commit(self) -> str | None:
        return self.commit_data.get("last_commit")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: v for k, v in self.data.items() if k != "last_commit"}
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
