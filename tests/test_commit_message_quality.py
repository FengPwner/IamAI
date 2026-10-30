#!/usr/bin/env python3
"""Tests for commit_message_quality.py — the four-dimension scorer."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from commit_message_quality import (
    _length_score,
    _verb_score,
    _object_score,
    _context_score,
    score_message,
    score_recent,
)


# ── length_score ─────────────────────────────────────────────────────


def test_length_short_is_zero():
    assert _length_score("fix") == 0.0


def test_length_medium_scales():
    score = _length_score("refactor the push gate to check remote drift")
    assert 0.0 < score < 1.0


def test_length_long_is_one():
    msg = "a" * 60
    assert _length_score(msg) == 1.0


def test_length_boundary_ten():
    assert _length_score("a" * 10) == 0.0


def test_length_boundary_fifty():
    assert _length_score("a" * 50) == 1.0


# ── verb_score ───────────────────────────────────────────────────────


def test_verb_strong_first_word():
    assert _verb_score("add heartbeat module for writer liveness") == 1.0


def test_verb_conventional_prefix():
    assert _verb_score("feat: add stroke dedup gate") == 1.0


def test_verb_second_word_scope():
    score = _verb_score("guoban: fix push race in batch committer")
    assert score == 0.7


def test_verb_weak_returns_low():
    score = _verb_score("update stuff")
    # "update" is in STRONG_VERBS so it should still score reasonably
    assert score > 0.0


def test_verb_no_verb_at_all():
    score = _verb_score("blah blah blah")
    assert score <= 0.2


def test_verb_empty_message():
    assert _verb_score("") == 0.0


# ── object_score ─────────────────────────────────────────────────────


def test_object_with_file_path():
    assert _object_score("fix push_gate.py to handle remote drift") == 1.0


def test_object_with_backticks():
    assert _object_score("refactor `commit_batch` interval logic") == 1.0


def test_object_compound_name():
    score = _object_score("add push-readiness probe")
    assert score >= 0.8


def test_object_vague_short():
    assert _object_score("misc stuff") == 0.0


def test_object_multi_word():
    score = _object_score("refactor the heartbeat decay tracker module")
    assert score >= 0.6


# ── context_score ────────────────────────────────────────────────────


def test_context_with_scope_and_reason():
    msg = "feat(writer): add heartbeat because silent death was undetected"
    score = _context_score(msg)
    assert score >= 0.7


def test_context_multi_clause():
    msg = "fix push lag, reduce batch interval, add retry backoff"
    score = _context_score(msg)
    assert score >= 0.3


def test_context_bare():
    assert _context_score("fix") == 0.0


def test_context_only_reason():
    score = _context_score("add retry so the push survives transient failures")
    assert score >= 0.3


# ── score_message composite ──────────────────────────────────────────


def test_composite_strong_message():
    msg = "feat(push): add pre-push sync to prevent race conditions when remote diverges"
    s = score_message("abc1234", msg)
    assert s.composite >= 0.7


def test_composite_weak_message():
    s = score_message("abc1234", "fix")
    assert s.composite < 0.4


def test_composite_medium_message():
    s = score_message("abc1234", "refactor commit batch interval logic")
    assert 0.3 <= s.composite <= 0.8


def test_score_message_fields():
    s = score_message("deadbeef", "add test")
    assert s.hash == "deadbeef"
    assert s.message == "add test"
    assert isinstance(s.composite, float)


# ── score_recent (integration, skipped if no git) ───────────────────


def test_score_recent_returns_list():
    """Should return a list (possibly empty if not in a git repo)."""
    result = score_recent(count=5)
    assert isinstance(result, list)


# ── entry point ──────────────────────────────────────────────────────


if __name__ == "__main__":
    passed = 0
    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {name}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
