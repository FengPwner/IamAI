"""Tests for snippets/wal.py — minimal write-ahead log."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from wal import CorruptEntry, WAL  # noqa: E402


@pytest.fixture
def wal_path(tmp_path: Path) -> Path:
    return tmp_path / "test.jsonl"


@pytest.fixture
def log(wal_path: Path) -> WAL:
    return WAL(wal_path)


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


def test_repr(log):
    assert "WAL" in repr(log)
    assert "checkpoint=0" in repr(log)


def test_empty_log_len(log):
    assert len(log) == 0


def test_checkpoint_starts_at_zero(log):
    assert log.checkpoint_seq == 0


# ---------------------------------------------------------------------------
# append
# ---------------------------------------------------------------------------


def test_append_returns_increasing_seq(log):
    s1 = log.append({"op": "set", "key": "x"})
    s2 = log.append({"op": "set", "key": "y"})
    assert s1 < s2


def test_append_starts_at_one(log):
    assert log.append({"first": True}) == 1


def test_append_increments_len(log):
    log.append({"a": 1})
    log.append({"b": 2})
    assert len(log) == 2


def test_append_creates_file(log, wal_path):
    log.append({"hello": "world"})
    assert wal_path.exists()


def test_append_persists_json_lines(log, wal_path):
    log.append({"key": "alpha"})
    log.append({"key": "beta"})
    lines = wal_path.read_text().strip().split("\n")
    assert len(lines) == 2
    r0 = json.loads(lines[0])
    assert r0["data"] == {"key": "alpha"}
    assert r0["seq"] == 1


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------


def test_replay_empty(log):
    assert list(log.replay()) == []


def test_replay_returns_all_entries(log):
    log.append({"n": 1})
    log.append({"n": 2})
    log.append({"n": 3})
    entries = list(log.replay())
    assert [e["data"]["n"] for e in entries] == [1, 2, 3]


def test_replay_preserves_order(log):
    for i in range(10):
        log.append({"i": i})
    entries = list(log.replay())
    assert [e["data"]["i"] for e in entries] == list(range(10))


def test_replay_skips_checkpointed_entries(log):
    s1 = log.append({"phase": "a"})
    s2 = log.append({"phase": "b"})
    s3 = log.append({"phase": "c"})
    log.checkpoint(s2)
    entries = list(log.replay())
    assert len(entries) == 1
    assert entries[0]["data"]["phase"] == "c"


def test_replay_corrupt_line_raises(log, wal_path):
    log.append({"good": True})
    # Inject a corrupt line.
    with open(wal_path, "a") as f:
        f.write("NOT JSON\n")
    log.append({"also_good": True})
    with pytest.raises(CorruptEntry):
        list(log.replay())


# ---------------------------------------------------------------------------
# checkpoint
# ---------------------------------------------------------------------------


def test_checkpoint_advances_watermark(log):
    s = log.append({"x": 1})
    log.checkpoint(s)
    assert log.checkpoint_seq == s


def test_checkpoint_is_monotonic(log):
    s1 = log.append({"a": 1})
    s2 = log.append({"b": 2})
    log.checkpoint(s2)
    log.checkpoint(s1)  # lower seq — no-op
    assert log.checkpoint_seq == s2


def test_checkpoint_persists_to_disk(log, wal_path):
    s = log.append({"persist": True})
    log.checkpoint(s)
    # Reopen: checkpoint should survive.
    log2 = WAL(wal_path)
    assert log2.checkpoint_seq == s


def test_checkpoint_idempotent(log):
    s = log.append({"once": True})
    log.checkpoint(s)
    log.checkpoint(s)  # same seq — no-op
    assert log.checkpoint_seq == s


# ---------------------------------------------------------------------------
# truncate
# ---------------------------------------------------------------------------


def test_truncate_removes_checkpointed_entries(log):
    s1 = log.append({"keep": False})
    s2 = log.append({"keep": False})
    s3 = log.append({"keep": True})
    log.checkpoint(s2)
    kept = log.truncate()
    assert kept == 1
    assert len(log) == 1
    entries = list(log.replay())
    assert entries[0]["data"]["keep"] is True


def test_truncate_empty_log(log):
    assert log.truncate() == 0


def test_truncate_all_checkpointed(log):
    s1 = log.append({"old": 1})
    s2 = log.append({"old": 2})
    log.checkpoint(s2)
    assert log.truncate() == 0
    assert len(log) == 0


def test_truncate_none_checkpointed(log):
    log.append({"new": 1})
    log.append({"new": 2})
    # checkpoint at 0 → nothing is checkpointed
    assert log.truncate() == 2


def test_truncate_drops_corrupt_lines(log, wal_path):
    log.append({"good": 1})
    with open(wal_path, "a") as f:
        f.write("BROKEN LINE\n")
    log.append({"good": 2})
    log.checkpoint(0)
    # truncate should drop the corrupt line and keep both good ones
    kept = log.truncate()
    assert kept == 2


# ---------------------------------------------------------------------------
# concurrent append (thread safety)
# ---------------------------------------------------------------------------


def test_concurrent_appends(log):
    """Multiple threads appending concurrently should produce unique seqs."""
    seqs: list[int] = []
    lock = threading.Lock()

    def writer(n: int):
        for i in range(20):
            s = log.append({"thread": n, "i": i})
            with lock:
                seqs.append(s)

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All 80 seqs should be unique.
    assert len(set(seqs)) == 80
    assert len(log) == 80


# ---------------------------------------------------------------------------
# end-to-end recovery scenario
# ---------------------------------------------------------------------------


def test_recovery_scenario(wal_path):
    """Simulate write → crash → reopen → replay → checkpoint → truncate."""
    # Phase 1: normal operation.
    log = WAL(wal_path)
    log.append({"op": "insert", "id": 1, "value": "hello"})
    log.append({"op": "insert", "id": 2, "value": "world"})
    log.append({"op": "update", "id": 1, "value": "HELLO"})
    s3 = log.append({"op": "delete", "id": 2})

    # Phase 2: "crash" — just reopen without checkpointing.
    log2 = WAL(wal_path)
    entries = list(log2.replay())
    assert len(entries) == 4  # all four entries need replay

    # Phase 3: apply entries, checkpoint at s3.
    state: dict[int, str] = {}
    for e in entries:
        op = e["data"]["op"]
        eid = e["data"]["id"]
        if op == "insert" or op == "update":
            state[eid] = e["data"]["value"]
        elif op == "delete":
            state.pop(eid, None)
    assert state == {1: "HELLO"}

    log2.checkpoint(s3)

    # Phase 4: truncate and verify clean slate.
    log2.truncate()
    assert len(log2) == 0
    assert list(log2.replay()) == []

    # Phase 5: continue writing after recovery.
    s5 = log2.append({"op": "insert", "id": 3, "value": "new"})
    assert s5 > s3
    assert list(log2.replay())[0]["data"]["id"] == 3
