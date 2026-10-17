"""Tests for iamai.writer_state — monotonic stroke-sequence contract.

Covers:
  - fresh / missing / corrupt state files start at seq 1
  - record() appends to the ledger
  - save() + load() round-trips correctly
  - next_seq() resumes from the highest recorded seq, not the count
  - non-dict entries in the strokes array are silently filtered
  - empty dict / non-dict JSON / missing file all degrade gracefully
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from iamai.writer_state import WriterState


@pytest.fixture
def tmp_dir():
    return Path(tempfile.mkdtemp())


# -- construction / load ---------------------------------------------------

class TestLoad:
    def test_missing_file_starts_fresh(self, tmp_dir):
        path = tmp_dir / "nonexistent.json"
        state = WriterState.load(path)
        assert state.next_seq() == 1

    def test_empty_file_starts_fresh(self, tmp_dir):
        path = tmp_dir / "state.json"
        path.write_text("", encoding="utf-8")
        state = WriterState.load(path)
        assert state.next_seq() == 1

    def test_empty_object_starts_fresh(self, tmp_dir):
        path = tmp_dir / "state.json"
        path.write_text("{}", encoding="utf-8")
        state = WriterState.load(path)
        assert state.next_seq() == 1

    def test_corrupt_json_starts_fresh(self, tmp_dir):
        path = tmp_dir / "state.json"
        path.write_text("{not valid json", encoding="utf-8")
        state = WriterState.load(path)
        assert state.next_seq() == 1

    def test_json_array_starts_fresh(self, tmp_dir):
        """Top-level value must be a dict; arrays are rejected."""
        path = tmp_dir / "state.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        state = WriterState.load(path)
        assert state.next_seq() == 1

    def test_strokes_not_a_list_filtered(self, tmp_dir):
        path = tmp_dir / "state.json"
        path.write_text('{"strokes": "not a list"}', encoding="utf-8")
        state = WriterState.load(path)
        assert state.next_seq() == 1

    def test_non_dict_strokes_filtered(self, tmp_dir):
        """Non-dict entries inside the strokes array are silently dropped."""
        path = tmp_dir / "state.json"
        data = {"strokes": [{"seq": 5, "kind": "note", "path": "a.md"}, 42, "skip", None]}
        path.write_text(json.dumps(data), encoding="utf-8")
        state = WriterState.load(path)
        assert state.next_seq() == 6  # only the valid entry counts

    def test_valid_state_loads(self, tmp_dir):
        data = {
            "strokes": [
                {"seq": 1, "kind": "thought", "path": "notes/a.md"},
                {"seq": 2, "kind": "note", "path": "notes/b.md"},
            ]
        }
        path = tmp_dir / "state.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        state = WriterState.load(path)
        assert state.next_seq() == 3


# -- record / next_seq -----------------------------------------------------

class TestRecordAndNextSeq:
    def test_record_increments_seq(self):
        state = WriterState()
        assert state.next_seq() == 1
        state.record(seq=1, kind="note", path="notes/a.md")
        assert state.next_seq() == 2

    def test_multiple_records(self):
        state = WriterState()
        for i in range(1, 6):
            state.record(seq=i, kind="thought", path=f"notes/{i}.md")
        assert state.next_seq() == 6

    def test_next_seq_uses_max_not_count(self):
        """If seqs are non-contiguous (e.g. after manual edit), next_seq uses max."""
        state = WriterState([
            {"seq": 10, "kind": "note", "path": "a.md"},
            {"seq": 3, "kind": "note", "path": "b.md"},
        ])
        assert state.next_seq() == 11

    def test_record_with_string_seq_coerced(self):
        """record() coerces seq to int."""
        state = WriterState()
        state.record(seq="7", kind="garden", path="docs/g.md")
        assert state.next_seq() == 8


# -- save / round-trip -----------------------------------------------------

class TestSaveRoundTrip:
    def test_save_and_reload(self, tmp_dir):
        path = tmp_dir / "state.json"
        state = WriterState()
        state.record(seq=1, kind="thought", path="notes/a.md")
        state.record(seq=2, kind="note", path="notes/b.md")
        state.save(path)

        reloaded = WriterState.load(path)
        assert reloaded.next_seq() == 3

    def test_saved_file_is_valid_json(self, tmp_dir):
        path = tmp_dir / "state.json"
        state = WriterState()
        state.record(seq=1, kind="devlog", path="docs/d.md")
        state.save(path)

        raw = json.loads(path.read_text(encoding="utf-8"))
        assert "strokes" in raw
        assert len(raw["strokes"]) == 1
        assert raw["strokes"][0]["seq"] == 1

    def test_round_trip_preserves_all_fields(self, tmp_dir):
        path = tmp_dir / "state.json"
        state = WriterState()
        state.record(seq=42, kind="snippet", path="notes/s.md")
        state.save(path)

        reloaded = WriterState.load(path)
        strokes = reloaded._strokes
        assert len(strokes) == 1
        assert strokes[0] == {"seq": 42, "kind": "snippet", "path": "notes/s.md"}

    def test_overwrite_existing_file(self, tmp_dir):
        path = tmp_dir / "state.json"
        s1 = WriterState()
        s1.record(seq=1, kind="note", path="a.md")
        s1.save(path)

        s2 = WriterState()
        s2.record(seq=100, kind="thought", path="b.md")
        s2.save(path)

        reloaded = WriterState.load(path)
        assert reloaded.next_seq() == 101
        assert len(reloaded._strokes) == 1


# -- edge cases ------------------------------------------------------------

class TestEdgeCases:
    def test_empty_strokes_list(self):
        state = WriterState([])
        assert state.next_seq() == 1

    def test_none_strokes_treated_as_empty(self):
        state = WriterState(None)
        assert state.next_seq() == 1

    def test_stroke_with_missing_seq_key(self):
        """A dict without 'seq' should not crash next_seq()."""
        state = WriterState([{"kind": "note", "path": "a.md"}])
        # .get("seq", 0) fallback means max is 0, so next is 1
        assert state.next_seq() == 1

    def test_large_sequence(self):
        state = WriterState()
        state.record(seq=999999, kind="metrics", path="docs/m.md")
        assert state.next_seq() == 1000000
