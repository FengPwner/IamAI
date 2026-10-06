"""Test that writer restart produces monotonically increasing stroke sequences.

After a container reclamation or process crash, the writer must resume from
the last recorded sequence number — never repeat, never skip. This test
validates the state-loading and sequence-continuity contract that keeps the
append-only log honest across restarts.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from iamai.writer_state import WriterState


class TestRestartSequenceContinuity:
    """When the writer restarts, the next stroke seq must be exactly
    last_recorded_seq + 1. Gaps indicate lost strokes; repeats indicate
    duplicate writes — both corrupt the append-only log."""

    def test_fresh_state_starts_at_one(self, tmp_path: Path):
        """A brand-new writer state with no history starts at seq 1."""
        state_file = tmp_path / "state.json"
        state = WriterState.load(state_file)
        assert state.next_seq() == 1

    def test_resume_after_history(self, tmp_path: Path):
        """After recording strokes 1..N, next_seq must return N+1."""
        state_file = tmp_path / "state.json"
        state = WriterState.load(state_file)

        # Simulate 5 strokes
        for i in range(1, 6):
            state.record(seq=i, kind="thought", path="notes/test.md")
        state.save(state_file)

        # Reload (simulating restart)
        reloaded = WriterState.load(state_file)
        assert reloaded.next_seq() == 6

    def test_no_seq_gap_after_reload(self, tmp_path: Path):
        """Reload must not introduce gaps — the seq after reload must be
        exactly one more than the last recorded seq."""
        state_file = tmp_path / "state.json"
        state = WriterState.load(state_file)

        last_seq = 42
        for i in range(1, last_seq + 1):
            state.record(seq=i, kind="note", path="notes/test.md")
        state.save(state_file)

        reloaded = WriterState.load(state_file)
        assert reloaded.next_seq() == last_seq + 1

    def test_empty_history_file(self, tmp_path: Path):
        """An empty or corrupt state file should start fresh, not crash."""
        state_file = tmp_path / "state.json"
        state_file.write_text("{}")

        state = WriterState.load(state_file)
        assert state.next_seq() == 1

    def test_state_persists_across_saves(self, tmp_path: Path):
        """Multiple save/load cycles must not drift the sequence counter."""
        state_file = tmp_path / "state.json"

        for cycle in range(3):
            state = WriterState.load(state_file)
            start = state.next_seq()
            for i in range(start, start + 10):
                state.record(seq=i, kind="thought", path="notes/test.md")
            state.save(state_file)

        final = WriterState.load(state_file)
        assert final.next_seq() == 31  # 3 cycles × 10 strokes each
