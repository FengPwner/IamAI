#!/usr/bin/env python3
"""tests for scripts/repo_coherence.py — commit narrative coherence analyzer."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from repo_coherence import (
    tokenize,
    score_topic_continuity,
    score_file_locality,
    score_intent_consistency,
    score_narrative_thread,
    compute_coherence_score,
    format_bar,
)


def _make_commit(msg, files=None, ts="2026-01-01T00:00:00+00:00"):
    """helper: build a commit dict with message and files."""
    return {
        "hash": "abc12345",
        "message": msg,
        "timestamp": ts,
        "files": files or [],
    }


# ── tokenizer ────────────────────────────────────────────────────────


class TestTokenize:
    def test_basic_extraction(self):
        tokens = tokenize("add repo_coherence.py module")
        assert "repo" in tokens
        assert "coherence" in tokens
        assert "module" in tokens

    def test_drops_short_words(self):
        tokens = tokenize("fix a bug in the code")
        assert "bug" in tokens
        assert "code" in tokens
        assert "fix" not in tokens  # stop word
        assert "the" not in tokens  # stop word + too short

    def test_drops_stop_words(self):
        tokens = tokenize("update the documentation for the new feature")
        assert "documentation" in tokens
        assert "feature" in tokens
        assert "update" not in tokens  # stop word
        assert "the" not in tokens
        assert "for" not in tokens

    def test_lowercase_normalization(self):
        tokens = tokenize("Add REPO_Coherence Module")
        assert "repo" in tokens
        assert "coherence" in tokens
        assert "module" in tokens

    def test_empty_string(self):
        tokens = tokenize("")
        assert tokens == set()

    def test_only_stop_words(self):
        tokens = tokenize("the and for with")
        assert tokens == set()


# ── topic continuity ─────────────────────────────────────────────────


class TestTopicContinuity:
    def test_identical_messages(self):
        """repeated messages should give perfect continuity (0 score)."""
        commits = [
            _make_commit("add coherence analysis module",
                         ts=f"2026-01-01T{i:02d}:00:00+00:00")
            for i in range(5)
        ]
        score = score_topic_continuity(commits)
        assert score == 0.0, f"identical messages should give 0, got {score}"

    def test_completely_disjoint(self):
        """no shared words between consecutive commits → worst score."""
        commits = [
            _make_commit("alpha beta gamma", ts="2026-01-01T00:00:00+00:00"),
            _make_commit("delta epsilon zeta", ts="2026-01-01T01:00:00+00:00"),
            _make_commit("theta iota kappa", ts="2026-01-01T02:00:00+00:00"),
            _make_commit("lambda muomicron", ts="2026-01-01T03:00:00+00:00"),
        ]
        score = score_topic_continuity(commits)
        assert score == 25.0, f"all disjoint should give 25, got {score}"

    def test_partial_overlap(self):
        """some shared words → moderate score."""
        commits = [
            _make_commit("add coherence analysis module",
                         ts="2026-01-01T00:00:00+00:00"),
            _make_commit("add coherence testing framework",
                         ts="2026-01-01T01:00:00+00:00"),
            _make_commit("update analysis documentation",
                         ts="2026-01-01T02:00:00+00:00"),
        ]
        score = score_topic_continuity(commits)
        assert 0 < score < 25, f"partial overlap should be moderate, got {score}"

    def test_empty_commits(self):
        """too few commits → neutral score."""
        score = score_topic_continuity([])
        assert score == 12.5

    def test_single_commit(self):
        """one commit → neutral score."""
        commits = [_make_commit("add feature")]
        score = score_topic_continuity(commits)
        assert score == 12.5


# ── file locality ────────────────────────────────────────────────────


class TestFileLocality:
    def test_same_directory(self):
        """all commits touch same directory → perfect locality (0 score)."""
        commits = [
            _make_commit("add feature", files=["scripts/foo.py", "scripts/bar.py"],
                         ts="2026-01-01T00:00:00+00:00"),
            _make_commit("fix bug", files=["scripts/baz.py"],
                         ts="2026-01-01T01:00:00+00:00"),
            _make_commit("update module", files=["scripts/qux.py"],
                         ts="2026-01-01T02:00:00+00:00"),
        ]
        score = score_file_locality(commits)
        assert score == 0.0, f"same dir should give 0, got {score}"

    def test_completely_different_directories(self):
        """each commit touches different directories → worst score."""
        commits = [
            _make_commit("add feature", files=["scripts/foo.py"],
                         ts="2026-01-01T00:00:00+00:00"),
            _make_commit("update docs", files=["notes/readme.md"],
                         ts="2026-01-01T01:00:00+00:00"),
            _make_commit("fix test", files=["tests/test_bar.py"],
                         ts="2026-01-01T02:00:00+00:00"),
            _make_commit("add data", files=["data/strokes.jsonl"],
                         ts="2026-01-01T03:00:00+00:00"),
        ]
        score = score_file_locality(commits)
        assert score == 25.0, f"all different dirs should give 25, got {score}"

    def test_partial_overlap(self):
        """some shared directories → moderate score."""
        commits = [
            _make_commit("add feature", files=["scripts/foo.py", "tests/test_foo.py"],
                         ts="2026-01-01T00:00:00+00:00"),
            _make_commit("fix bug", files=["scripts/bar.py", "docs/readme.md"],
                         ts="2026-01-01T01:00:00+00:00"),
        ]
        score = score_file_locality(commits)
        assert 0 < score < 25, f"partial overlap should be moderate, got {score}"

    def test_empty_commits(self):
        """too few commits → neutral score."""
        score = score_file_locality([])
        assert score == 12.5

    def test_root_directory_files(self):
        """files without directory should be treated as root."""
        commits = [
            _make_commit("add readme", files=["README.md"],
                         ts="2026-01-01T00:00:00+00:00"),
            _make_commit("add license", files=["LICENSE"],
                         ts="2026-01-01T01:00:00+00:00"),
        ]
        score = score_file_locality(commits)
        assert score == 0.0, f"root files should share '.', got {score}"


# ── intent consistency ───────────────────────────────────────────────


class TestIntentConsistency:
    def test_stable_intent(self):
        """all commits have same intent prefix → low score."""
        commits = [
            _make_commit(f"add feature {i}",
                         ts=f"2026-01-01T{i:02d}:00:00+00:00")
            for i in range(20)
        ]
        score = score_intent_consistency(commits)
        assert score < 5, f"stable intent should be low, got {score}"

    def test_shifting_intent(self):
        """first half all 'add', second half all 'fix' → high score."""
        commits = []
        for i in range(10):
            commits.append(_make_commit(f"add feature {i}",
                                        ts=f"2026-01-01T{i:02d}:00:00+00:00"))
        for i in range(10, 20):
            commits.append(_make_commit(f"fix bug {i}",
                                        ts=f"2026-01-01T{i:02d}:00:00+00:00"))
        score = score_intent_consistency(commits)
        assert score > 15, f"shifting intent should be high, got {score}"

    def test_mixed_intent(self):
        """random mix of intents → moderate score."""
        prefixes = ["add", "fix", "update", "refactor", "docs"]
        commits = [
            _make_commit(f"{prefixes[i % len(prefixes)]} something {i}",
                         ts=f"2026-01-01T{i:02d}:00:00+00:00")
            for i in range(20)
        ]
        score = score_intent_consistency(commits)
        # mixed but stable → should be moderate
        assert 0 <= score <= 25, f"score out of range: {score}"

    def test_too_few_commits(self):
        """too few commits → neutral score."""
        commits = [_make_commit("add feature")]
        score = score_intent_consistency(commits)
        assert score == 12.5


# ── narrative thread ─────────────────────────────────────────────────


class TestNarrativeThread:
    def test_all_connected(self):
        """every consecutive pair shares a word → perfect thread (0 score)."""
        commits = [
            _make_commit("add coherence analysis module",
                         ts="2026-01-01T00:00:00+00:00"),
            _make_commit("update coherence testing framework",
                         ts="2026-01-01T01:00:00+00:00"),
            _make_commit("fix coherence scoring logic",
                         ts="2026-01-01T02:00:00+00:00"),
        ]
        score = score_narrative_thread(commits)
        assert score == 0.0, f"all connected should give 0, got {score}"

    def test_none_connected(self):
        """no consecutive pair shares a word → worst score."""
        commits = [
            _make_commit("alpha beta gamma", ts="2026-01-01T00:00:00+00:00"),
            _make_commit("delta epsilon zeta", ts="2026-01-01T01:00:00+00:00"),
            _make_commit("theta iota kappa", ts="2026-01-01T02:00:00+00:00"),
        ]
        score = score_narrative_thread(commits)
        assert score == 25.0, f"none connected should give 25, got {score}"

    def test_half_connected(self):
        """half the pairs connected → moderate score."""
        commits = [
            _make_commit("alpha beta gamma", ts="2026-01-01T00:00:00+00:00"),
            _make_commit("alpha delta epsilon", ts="2026-01-01T01:00:00+00:00"),  # shares 'alpha'
            _make_commit("zeta theta iota", ts="2026-01-01T02:00:00+00:00"),  # disjoint
            _make_commit("kappa lambda muomicron", ts="2026-01-01T03:00:00+00:00"),  # disjoint
        ]
        score = score_narrative_thread(commits)
        # 1 connected out of 3 pairs = 0.333 ratio → (1-0.333)*25 ≈ 16.67
        assert 10 < score < 20, f"half connected should be moderate, got {score}"

    def test_empty_commits(self):
        """too few commits → neutral score."""
        score = score_narrative_thread([])
        assert score == 12.5


# ── scoring & grading ────────────────────────────────────────────────


class TestCoherenceScoring:
    def test_perfect_coherence(self):
        """all metrics 0 → total 0, COHERENT."""
        total, grade = compute_coherence_score(0, 0, 0, 0)
        assert total == 0.0
        assert grade == "COHERENT"

    def test_worst_coherence(self):
        """all metrics 25 → total 100, FRAGMENTED."""
        total, grade = compute_coherence_score(25, 25, 25, 25)
        assert total == 100.0
        assert grade == "FRAGMENTED"

    def test_moderate_coherence(self):
        """moderate metrics → FOCUSED or WANDERING."""
        total, grade = compute_coherence_score(10, 12, 8, 15)
        assert 40 < total < 50
        assert grade in ("FOCUSED", "WANDERING")

    def test_grade_boundaries(self):
        """check grade thresholds."""
        _, grade1 = compute_coherence_score(5, 5, 5, 5)
        assert grade1 == "COHERENT"

        _, grade2 = compute_coherence_score(10, 10, 10, 10)
        assert grade2 == "FOCUSED"

        _, grade3 = compute_coherence_score(15, 15, 15, 15)
        assert grade3 == "WANDERING"

        _, grade4 = compute_coherence_score(20, 20, 20, 20)
        assert grade4 == "FRAGMENTED"


class TestFormatBar:
    def test_zero_value(self):
        bar = format_bar(0, 25, 20)
        assert bar == "░" * 20

    def test_max_value(self):
        bar = format_bar(25, 25, 20)
        assert bar == "█" * 20

    def test_half_value(self):
        bar = format_bar(12.5, 25, 20)
        assert "█" in bar
        assert "░" in bar
        assert len(bar) == 20
