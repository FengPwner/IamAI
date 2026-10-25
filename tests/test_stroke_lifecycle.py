"""Tests for iamai.stroke_lifecycle."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from iamai.stroke_lifecycle import (
    _STROKES_REL,
    _CommitMap,
    _build_commit_map,
    _committed_seqs,
    _current_jsonl_seqs,
    _find_commit_for_seq,
    _has_uncommitted_changes,
    _pushed_seqs,
    _run,
    lifecycle,
    lifecycle_report,
    lifecycle_stats,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_strokes_jsonl(tmp_path: Path, strokes: list[dict]) -> Path:
    """Write a strokes.jsonl and return its path."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / "strokes.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for s in strokes:
            f.write(json.dumps(s) + "\n")
    return p


def _stroke(seq: int, kind: str = "thought", text: str = "test") -> dict:
    return {"seq": seq, "at": "2026-10-15T00:00:00+00:00", "kind": kind, "text": text}


def _make_commit_map(
    entries: dict[str, set[int]] | None = None,
    pushed: set[str] | None = None,
) -> _CommitMap:
    cm = _CommitMap()
    cm.entries = entries or {}
    cm.pushed_commits = pushed or set()
    cm.built = True
    return cm


# ---------------------------------------------------------------------------
# _run
# ---------------------------------------------------------------------------


class TestRun:
    def test_basic_command(self, tmp_path):
        result = _run(["echo", "hello"], tmp_path)
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_failing_command(self, tmp_path):
        result = _run(["false"], tmp_path)
        assert result.returncode != 0

    def test_cwd_respected(self, tmp_path):
        result = _run(["pwd"], tmp_path)
        assert str(tmp_path) in result.stdout


# ---------------------------------------------------------------------------
# _current_jsonl_seqs
# ---------------------------------------------------------------------------


class TestCurrentJsonlSeqs:
    def test_empty_repo(self, tmp_path):
        assert _current_jsonl_seqs(tmp_path) == set()

    def test_reads_seqs(self, tmp_path):
        _make_strokes_jsonl(tmp_path, [_stroke(1), _stroke(5), _stroke(10)])
        assert _current_jsonl_seqs(tmp_path) == {1, 5, 10}

    def test_skips_malformed_lines(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        p = data_dir / "strokes.jsonl"
        p.write_text('{"seq": 1, "kind": "thought"}\nnot-json\n{"seq": 3}\n')
        assert _current_jsonl_seqs(tmp_path) == {1, 3}

    def test_skips_entries_without_seq(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        p = data_dir / "strokes.jsonl"
        p.write_text('{"kind": "thought"}\n{"seq": 2}\n')
        assert _current_jsonl_seqs(tmp_path) == {2}

    def test_empty_file(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "strokes.jsonl").write_text("")
        assert _current_jsonl_seqs(tmp_path) == set()

    def test_blank_lines_skipped(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "strokes.jsonl").write_text('{"seq": 1}\n\n\n{"seq": 2}\n')
        assert _current_jsonl_seqs(tmp_path) == {1, 2}


# ---------------------------------------------------------------------------
# _committed_seqs / _pushed_seqs
# ---------------------------------------------------------------------------


class TestCommittedSeqs:
    def test_empty_map(self):
        cm = _make_commit_map()
        assert _committed_seqs(cm) == set()

    def test_single_commit(self):
        cm = _make_commit_map({"abc123": {1, 2, 3}})
        assert _committed_seqs(cm) == {1, 2, 3}

    def test_multiple_commits(self):
        cm = _make_commit_map({"abc": {1, 2}, "def": {3, 4}})
        assert _committed_seqs(cm) == {1, 2, 3, 4}

    def test_overlapping_seqs(self):
        cm = _make_commit_map({"abc": {1, 2}, "def": {2, 3}})
        assert _committed_seqs(cm) == {1, 2, 3}


class TestPushedSeqs:
    def test_no_pushed_commits(self):
        cm = _make_commit_map({"abc": {1, 2}})
        assert _pushed_seqs(cm) == set()

    def test_some_pushed(self):
        cm = _make_commit_map(
            {"abc": {1, 2}, "def": {3, 4}},
            pushed={"abc"},
        )
        assert _pushed_seqs(cm) == {1, 2}

    def test_all_pushed(self):
        cm = _make_commit_map(
            {"abc": {1}, "def": {2}},
            pushed={"abc", "def"},
        )
        assert _pushed_seqs(cm) == {1, 2}


# ---------------------------------------------------------------------------
# _find_commit_for_seq
# ---------------------------------------------------------------------------


class TestFindCommitForSeq:
    def test_found(self):
        cm = _make_commit_map({"abc": {1, 2}, "def": {3, 4}})
        assert _find_commit_for_seq(3, cm) == "def"

    def test_not_found(self):
        cm = _make_commit_map({"abc": {1, 2}})
        assert _find_commit_for_seq(99, cm) is None

    def test_empty_map(self):
        cm = _make_commit_map()
        assert _find_commit_for_seq(1, cm) is None

    def test_first_seq_in_commit(self):
        cm = _make_commit_map({"first": {1, 2, 3}})
        assert _find_commit_for_seq(1, cm) == "first"

    def test_seq_in_multiple_commits_returns_first(self):
        # In practice a seq should only appear once, but handle gracefully
        cm = _make_commit_map({"a": {1}, "b": {1}})
        result = _find_commit_for_seq(1, cm)
        assert result in ("a", "b")


# ---------------------------------------------------------------------------
# _has_uncommitted_changes
# ---------------------------------------------------------------------------


class TestHasUncommittedChanges:
    @patch("iamai.stroke_lifecycle._run")
    def test_clean_tree(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        assert _has_uncommitted_changes(Path("/fake")) is False

    @patch("iamai.stroke_lifecycle._run")
    def test_dirty_tree(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=" M data/strokes.jsonl\n")
        assert _has_uncommitted_changes(Path("/fake")) is True

    @patch("iamai.stroke_lifecycle._run")
    def test_git_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=128, stdout="")
        assert _has_uncommitted_changes(Path("/fake")) is False

    @patch("iamai.stroke_lifecycle._run")
    def test_whitespace_only(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="  \n  ")
        assert _has_uncommitted_changes(Path("/fake")) is False


# ---------------------------------------------------------------------------
# _build_commit_map
# ---------------------------------------------------------------------------


class TestBuildCommitMap:
    @patch("iamai.stroke_lifecycle._run")
    def test_no_strokes_file(self, mock_run, tmp_path):
        cm = _build_commit_map(tmp_path)
        assert cm.built is True
        assert cm.entries == {}

    @patch("iamai.stroke_lifecycle._run")
    def test_git_log_fails(self, mock_run, tmp_path):
        _make_strokes_jsonl(tmp_path, [_stroke(1)])
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        cm = _build_commit_map(tmp_path)
        assert cm.built is True
        assert cm.entries == {}

    @patch("iamai.stroke_lifecycle._run")
    def test_single_commit_with_stroke(self, mock_run, tmp_path):
        _make_strokes_jsonl(tmp_path, [_stroke(1)])

        def side_effect(cmd, cwd):
            cmd_str = " ".join(cmd)
            if "log" in cmd and "--format=%H" in cmd and "origin" not in cmd:
                return MagicMock(returncode=0, stdout="abc123\n")
            elif "origin" in cmd_str:
                return MagicMock(returncode=0, stdout="abc123\n")
            elif "diff" in cmd:
                diff_output = '+{"seq": 1, "at": "2026-10-15T00:00:00+00:00", "kind": "thought", "text": "test"}\n'
                return MagicMock(returncode=0, stdout=diff_output)
            return MagicMock(returncode=0, stdout="")

        mock_run.side_effect = side_effect
        cm = _build_commit_map(tmp_path)
        assert cm.built is True
        assert 1 in cm.entries.get("abc123", set())


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_pushed_state(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map(
            {"abc": {10}}, pushed={"abc"}
        )
        mock_seqs.return_value = {10}
        mock_dirty.return_value = False

        result = lifecycle(seq=10, repo=Path("/fake"))
        assert result["state"] == "pushed"
        assert result["pushed"] is True
        assert result["commit"] == "abc"
        assert result["in_jsonl"] is True

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_committed_state(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map({"abc": {10}})
        mock_seqs.return_value = {10}
        mock_dirty.return_value = False

        result = lifecycle(seq=10, repo=Path("/fake"))
        assert result["state"] == "committed"
        assert result["pushed"] is False
        assert result["commit"] == "abc"

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_written_state_dirty(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map()
        mock_seqs.return_value = {10}
        mock_dirty.return_value = True

        result = lifecycle(seq=10, repo=Path("/fake"))
        assert result["state"] == "written"
        assert result["commit"] is None

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_written_state_clean_tree(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map()
        mock_seqs.return_value = {10}
        mock_dirty.return_value = False

        result = lifecycle(seq=10, repo=Path("/fake"))
        assert result["state"] == "written"

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_orphaned_state(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map()
        mock_seqs.return_value = set()  # not in JSONL
        mock_dirty.return_value = False

        result = lifecycle(seq=10, repo=Path("/fake"))
        assert result["state"] == "orphaned"
        assert result["in_jsonl"] is False

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_default_repo_is_cwd(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map({"x": {1}}, pushed={"x"})
        mock_seqs.return_value = {1}
        mock_dirty.return_value = False

        result = lifecycle(seq=1)
        assert result["state"] == "pushed"

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_seq_field_in_result(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map()
        mock_seqs.return_value = {42}
        mock_dirty.return_value = True

        result = lifecycle(seq=42, repo=Path("/fake"))
        assert result["seq"] == 42


# ---------------------------------------------------------------------------
# lifecycle_stats
# ---------------------------------------------------------------------------


class TestLifecycleStats:
    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_all_pushed(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map(
            {"a": {1, 2, 3, 4, 5}}, pushed={"a"}
        )
        mock_seqs.return_value = {1, 2, 3, 4, 5}
        mock_dirty.return_value = False

        stats = lifecycle_stats(repo=Path("/fake"), last=5)
        assert stats["total"] == 5
        assert stats["pushed"] == 5
        assert stats["committed"] == 0
        assert stats["written"] == 0
        assert stats["orphaned"] == 0
        assert stats["push_rate"] == 1.0

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_mixed_states(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map(
            {"a": {1, 2}, "b": {3}}, pushed={"a"}
        )
        mock_seqs.return_value = {1, 2, 3, 4}
        mock_dirty.return_value = True

        stats = lifecycle_stats(repo=Path("/fake"), last=10)
        assert stats["total"] == 4
        assert stats["pushed"] == 2
        assert stats["committed"] == 1
        assert stats["written"] == 1

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_empty_jsonl(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map()
        mock_seqs.return_value = set()
        mock_dirty.return_value = False

        stats = lifecycle_stats(repo=Path("/fake"))
        assert stats["total"] == 0
        assert stats["push_rate"] == 0.0
        assert stats["commit_rate"] == 0.0

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_last_limits_window(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map(
            {"a": set(range(1, 101))}, pushed={"a"}
        )
        mock_seqs.return_value = set(range(1, 101))
        mock_dirty.return_value = False

        stats = lifecycle_stats(repo=Path("/fake"), last=10)
        assert stats["total"] == 10

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_push_rate_calculation(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map(
            {"a": {1, 2}, "b": {3, 4}}, pushed={"a"}
        )
        mock_seqs.return_value = {1, 2, 3, 4}
        mock_dirty.return_value = False

        stats = lifecycle_stats(repo=Path("/fake"), last=4)
        assert stats["push_rate"] == 0.5

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_commit_rate_includes_committed(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map(
            {"a": {1, 2}, "b": {3}}, pushed={"a"}
        )
        mock_seqs.return_value = {1, 2, 3, 4}
        mock_dirty.return_value = True

        stats = lifecycle_stats(repo=Path("/fake"), last=4)
        # pushed=2, committed=1, written=1 → commit_rate = 3/4
        assert stats["commit_rate"] == 0.75

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_detail_list(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map(
            {"a": {1, 2}}, pushed={"a"}
        )
        mock_seqs.return_value = {1, 2, 3}
        mock_dirty.return_value = True

        stats = lifecycle_stats(repo=Path("/fake"), last=3)
        assert len(stats["detail"]) == 3
        states = {d["seq"]: d["state"] for d in stats["detail"]}
        assert states[1] == "pushed"
        assert states[2] == "pushed"
        assert states[3] == "written"

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_default_repo(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map({"a": {1}}, pushed={"a"})
        mock_seqs.return_value = {1}
        mock_dirty.return_value = False

        stats = lifecycle_stats(last=1)
        assert stats["total"] == 1

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_orphaned_counted(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map()
        mock_seqs.return_value = set()  # nothing in JSONL
        mock_dirty.return_value = False

        # Since we only check seqs that ARE in the JSONL, orphaned count
        # comes from seqs in the detail that have no commit and aren't in JSONL.
        # With empty JSONL, total is 0.
        stats = lifecycle_stats(repo=Path("/fake"), last=10)
        assert stats["total"] == 0


# ---------------------------------------------------------------------------
# lifecycle_report
# ---------------------------------------------------------------------------


class TestLifecycleReport:
    @patch("iamai.stroke_lifecycle.lifecycle_stats")
    def test_format_all_pushed(self, mock_stats):
        mock_stats.return_value = {
            "total": 50,
            "pushed": 50,
            "committed": 0,
            "written": 0,
            "orphaned": 0,
            "push_rate": 1.0,
            "commit_rate": 1.0,
        }
        report = lifecycle_report(last=50)
        assert "50/50 pushed" in report
        assert "100%" in report
        assert "0 orphaned" in report

    @patch("iamai.stroke_lifecycle.lifecycle_stats")
    def test_format_partial(self, mock_stats):
        mock_stats.return_value = {
            "total": 50,
            "pushed": 40,
            "committed": 5,
            "written": 3,
            "orphaned": 2,
            "push_rate": 0.80,
            "commit_rate": 0.90,
        }
        report = lifecycle_report(last=50)
        assert "40/50 pushed" in report
        assert "5 committed" in report
        assert "3 written" in report
        assert "2 orphaned" in report
        assert "80%" in report

    @patch("iamai.stroke_lifecycle.lifecycle_stats")
    def test_format_empty(self, mock_stats):
        mock_stats.return_value = {
            "total": 0,
            "pushed": 0,
            "committed": 0,
            "written": 0,
            "orphaned": 0,
            "push_rate": 0.0,
            "commit_rate": 0.0,
        }
        report = lifecycle_report()
        assert "0/0 pushed" in report
        assert "0%" in report

    @patch("iamai.stroke_lifecycle.lifecycle_stats")
    def test_starts_with_lifecycle(self, mock_stats):
        mock_stats.return_value = {
            "total": 1,
            "pushed": 1,
            "committed": 0,
            "written": 0,
            "orphaned": 0,
            "push_rate": 1.0,
            "commit_rate": 1.0,
        }
        report = lifecycle_report()
        assert report.startswith("lifecycle:")

    @patch("iamai.stroke_lifecycle.lifecycle_stats")
    def test_push_rate_format(self, mock_stats):
        mock_stats.return_value = {
            "total": 3,
            "pushed": 1,
            "committed": 1,
            "written": 1,
            "orphaned": 0,
            "push_rate": 0.3333,
            "commit_rate": 0.6667,
        }
        report = lifecycle_report()
        assert "33%" in report

    @patch("iamai.stroke_lifecycle.lifecycle_stats")
    def test_custom_last_parameter(self, mock_stats):
        mock_stats.return_value = {
            "total": 20,
            "pushed": 20,
            "committed": 0,
            "written": 0,
            "orphaned": 0,
            "push_rate": 1.0,
            "commit_rate": 1.0,
        }
        lifecycle_report(last=20)
        mock_stats.assert_called_once_with(repo=None, last=20)


# ---------------------------------------------------------------------------
# _CommitMap dataclass
# ---------------------------------------------------------------------------


class TestCommitMap:
    def test_defaults(self):
        cm = _CommitMap()
        assert cm.entries == {}
        assert cm.pushed_commits == set()
        assert cm.built is False

    def test_with_data(self):
        cm = _CommitMap(
            entries={"abc": {1, 2}},
            pushed_commits={"abc"},
            built=True,
        )
        assert cm.entries == {"abc": {1, 2}}
        assert cm.pushed_commits == {"abc"}
        assert cm.built is True

    def test_mutation(self):
        cm = _CommitMap()
        cm.entries["x"] = {10}
        cm.pushed_commits.add("x")
        assert 10 in cm.entries["x"]
        assert "x" in cm.pushed_commits


# ---------------------------------------------------------------------------
# edge cases and integration-style tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_large_seq_numbers(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map(
            {"abc": {999999}}, pushed={"abc"}
        )
        mock_seqs.return_value = {999999}
        mock_dirty.return_value = False

        result = lifecycle(seq=999999, repo=Path("/fake"))
        assert result["state"] == "pushed"

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_seq_zero(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map({"abc": {0}}, pushed={"abc"})
        mock_seqs.return_value = {0}
        mock_dirty.return_value = False

        result = lifecycle(seq=0, repo=Path("/fake"))
        assert result["state"] == "pushed"

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_negative_seq(self, mock_dirty, mock_seqs, mock_build):
        # Shouldn't happen in practice but shouldn't crash
        mock_build.return_value = _make_commit_map()
        mock_seqs.return_value = {-1}
        mock_dirty.return_value = True

        result = lifecycle(seq=-1, repo=Path("/fake"))
        assert result["state"] == "written"

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_many_commits_many_strokes(self, mock_dirty, mock_seqs, mock_build):
        entries = {}
        all_seqs = set()
        for i in range(50):
            commit_hash = f"commit_{i}"
            seqs = set(range(i * 10, (i + 1) * 10))
            entries[commit_hash] = seqs
            all_seqs |= seqs

        pushed_hashes = {f"commit_{i}" for i in range(45)}
        mock_build.return_value = _make_commit_map(entries, pushed=pushed_hashes)
        mock_seqs.return_value = all_seqs
        mock_dirty.return_value = False

        stats = lifecycle_stats(repo=Path("/fake"), last=500)
        assert stats["total"] == 500
        assert stats["pushed"] == 450  # 45 commits × 10 seqs
        assert stats["committed"] == 50  # 5 commits × 10 seqs

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_push_rate_rounds_to_four_decimals(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map(
            {"a": {1}}, pushed={"a"}
        )
        mock_seqs.return_value = {1, 2, 3}
        mock_dirty.return_value = True

        stats = lifecycle_stats(repo=Path("/fake"), last=3)
        # 1/3 = 0.3333...
        assert stats["push_rate"] == 0.3333
        # commit_rate: 1 pushed / 3 total = 0.3333
        assert stats["commit_rate"] == 0.3333

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_lifecycle_with_unpushed_and_pushed_in_same_commit(self, mock_dirty, mock_seqs, mock_build):
        # Edge case: commit has seqs, some pushed via different ref
        cm = _make_commit_map(
            {"abc": {1, 2, 3}}, pushed=set()
        )
        mock_build.return_value = cm
        mock_seqs.return_value = {1, 2, 3}
        mock_dirty.return_value = False

        # All committed but none pushed
        for seq in (1, 2, 3):
            result = lifecycle(seq=seq, repo=Path("/fake"))
            assert result["state"] == "committed"
            assert result["pushed"] is False

    @patch("iamai.stroke_lifecycle._build_commit_map")
    @patch("iamai.stroke_lifecycle._current_jsonl_seqs")
    @patch("iamai.stroke_lifecycle._has_uncommitted_changes")
    def test_stats_detail_has_all_seqs(self, mock_dirty, mock_seqs, mock_build):
        mock_build.return_value = _make_commit_map(
            {"a": {10, 20}}, pushed={"a"}
        )
        mock_seqs.return_value = {10, 20, 30}
        mock_dirty.return_value = True

        stats = lifecycle_stats(repo=Path("/fake"), last=10)
        detail_seqs = {d["seq"] for d in stats["detail"]}
        assert detail_seqs == {10, 20, 30}
