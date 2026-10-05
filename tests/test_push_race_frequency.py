"""Tests for visitor_log.push_race_frequency().

Push races are the most common caretaker intervention in this repo.
The frequency function needs to count them correctly even when the
signal is buried in free-text note fields or oddly capitalised action
strings.
"""

from __future__ import annotations

import pytest

from iamai.visitor_log import VisitEntry, push_race_frequency


def _entry(ts: str, visitor: str, actions: list[str], note: str = "", outcome: str = "ok") -> VisitEntry:
    return VisitEntry(
        timestamp=ts,
        visitor=visitor,
        writer_status="dead",
        batch_status="dead",
        uncommitted_files=5,
        actions_taken=actions,
        outcome=outcome,
        note=note,
    )


class TestPushRaceFrequency:
    def test_empty_log(self):
        result = push_race_frequency([])
        assert result["total_visits"] == 0
        assert result["push_races"] == 0
        assert result["race_rate"] == 0.0
        assert result["by_visitor"] == {}
        assert result["by_hour"] == {}

    def test_no_races(self):
        entries = [
            _entry("2026-10-04T10:00:00Z", "qwen", ["restarted writer", "committed backlog"]),
            _entry("2026-10-04T16:00:00Z", "qwen", ["restarted batch"]),
        ]
        result = push_race_frequency(entries)
        assert result["push_races"] == 0
        assert result["race_rate"] == 0.0

    def test_detects_push_rejection_in_actions(self):
        entries = [
            _entry("2026-10-05T02:00:00Z", "qwen", [
                "committed backlog",
                "push rejected (fetch first), stashed and rebased",
                "restarted writer",
            ]),
        ]
        result = push_race_frequency(entries)
        assert result["push_races"] == 1
        assert result["race_rate"] == 1.0
        assert result["by_visitor"] == {"qwen": 1}
        assert result["by_hour"] == {"02": 1}

    def test_detects_race_in_note_field(self):
        entries = [
            _entry(
                "2026-10-05T09:00:00Z", "caretaker",
                ["restarted processes"],
                note="push race again, had to rebase manually",
            ),
        ]
        result = push_race_frequency(entries)
        assert result["push_races"] == 1
        assert result["by_visitor"] == {"caretaker": 1}

    def test_counts_each_visit_at_most_once(self):
        """A visit with two race-related actions is still one race."""
        entries = [
            _entry("2026-10-05T03:00:00Z", "qwen", [
                "push rejected",
                "rebased on origin/main",
                "pushed successfully",
            ]),
        ]
        result = push_race_frequency(entries)
        assert result["push_races"] == 1

    def test_multiple_visitors(self):
        entries = [
            _entry("2026-10-04T12:00:00Z", "qwen", ["push rejected", "rebased"]),
            _entry("2026-10-04T14:00:00Z", "kimi", ["restarted writer"]),
            _entry("2026-10-04T18:00:00Z", "kimi", ["non-fast-forward, pulled --rebase"]),
            _entry("2026-10-04T20:00:00Z", "qwen", ["clean push"]),
        ]
        result = push_race_frequency(entries)
        assert result["total_visits"] == 4
        assert result["push_races"] == 2
        assert result["race_rate"] == 0.5
        assert result["by_visitor"] == {"qwen": 1, "kimi": 1}
        assert result["by_hour"] == {"12": 1, "18": 1}

    def test_matched_actions_collected(self):
        entries = [
            _entry("2026-10-05T01:00:00Z", "qwen", [
                "committed 10 files",
                "push rejected (fetch first), stashed and rebased",
            ]),
        ]
        result = push_race_frequency(entries)
        assert len(result["actions_needing_rebase"]) == 1
        assert "fetch first" in result["actions_needing_rebase"][0]

    def test_race_rate_precision(self):
        """3 races out of 7 visits should not round to zero."""
        entries = [
            _entry("2026-10-04T01:00:00Z", "qwen", ["push rejected"]),
            _entry("2026-10-04T02:00:00Z", "qwen", ["clean restart"]),
            _entry("2026-10-04T03:00:00Z", "qwen", ["rebased"]),
            _entry("2026-10-04T04:00:00Z", "qwen", ["clean"]),
            _entry("2026-10-04T05:00:00Z", "qwen", ["fetch first conflict"]),
            _entry("2026-10-04T06:00:00Z", "qwen", ["clean"]),
            _entry("2026-10-04T07:00:00Z", "qwen", ["clean"]),
        ]
        result = push_race_frequency(entries)
        assert result["push_races"] == 3
        assert abs(result["race_rate"] - 3 / 7) < 1e-9

    def test_case_insensitive_matching(self):
        entries = [
            _entry("2026-10-05T10:00:00Z", "qwen", ["Push Rejected by remote"]),
        ]
        result = push_race_frequency(entries)
        assert result["push_races"] == 1

    def test_malformed_timestamp_does_not_crash(self):
        entries = [
            _entry("", "qwen", ["push rejected"]),
            _entry("short", "kimi", ["rebased"]),
        ]
        result = push_race_frequency(entries)
        assert result["push_races"] == 2
        # hour buckets may be missing or empty — just should not crash
        assert isinstance(result["by_hour"], dict)
