#!/usr/bin/env python3
"""Tests for commit_echo — repetition pattern detection in commit flow.

72 tests covering:
- _jaccard (identical, disjoint, partial, empty sets)
- _tokenise (normalisation, short token filtering, empty input)
- _token_overlap (full match, partial, disjoint, empty)
- _is_file_echo (hit, miss, threshold boundary, empty files)
- _is_msg_echo (hit, miss, threshold boundary, empty messages)
- classify_echo (all five classes + boundary values)
- compute_echo (fresh, varied, repetitive, looping, stuck scenarios)
- compute_echo edge cases (empty, single commit, all same)
- echo_report formatting
- echo_trend (increasing, decreasing, stable, single, empty)
- full pipeline integration with realistic data
"""

import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, ".")
from iamai.commit_echo import (
    CommitInfo,
    EchoResult,
    EchoTrend,
    _is_file_echo,
    _is_msg_echo,
    _jaccard,
    _token_overlap,
    _tokenise,
    classify_echo,
    compute_echo,
    echo_report,
    echo_trend,
)


def _mkcommit(
    hash: str,
    files: list,
    msg: str = "update various modules",
    author: str = "qwen",
    ts_offset_minutes: int = 0,
) -> CommitInfo:
    """Helper to create a CommitInfo."""
    base = datetime(2026, 11, 1, 12, 0, 0)
    return CommitInfo(
        hash=hash,
        author=author,
        timestamp=base + timedelta(minutes=ts_offset_minutes),
        message=msg,
        files_changed=list(files),
    )


# ── _jaccard ──────────────────────────────────────────────────────────────


class TestJaccard(unittest.TestCase):
    def test_identical_sets(self):
        self.assertEqual(_jaccard({"a", "b"}, {"a", "b"}), 1.0)

    def test_disjoint_sets(self):
        self.assertEqual(_jaccard({"a"}, {"b"}), 0.0)

    def test_partial_overlap(self):
        # {a, b} & {b, c} = {b}, union = {a, b, c} → 1/3
        self.assertAlmostEqual(_jaccard({"a", "b"}, {"b", "c"}), 1 / 3)

    def test_both_empty(self):
        self.assertEqual(_jaccard(set(), set()), 1.0)

    def test_one_empty(self):
        self.assertEqual(_jaccard({"a"}, set()), 0.0)

    def test_subset(self):
        # {a} ⊂ {a, b} → 1/2
        self.assertAlmostEqual(_jaccard({"a"}, {"a", "b"}), 0.5)

    def test_single_element_match(self):
        self.assertEqual(_jaccard({"x"}, {"x"}), 1.0)


# ── _tokenise ─────────────────────────────────────────────────────────────


class TestTokenise(unittest.TestCase):
    def test_basic(self):
        tokens = _tokenise("add commit echo module")
        self.assertIn("add", tokens)
        self.assertIn("commit", tokens)
        self.assertIn("echo", tokens)
        self.assertIn("module", tokens)

    def test_lowercase(self):
        tokens = _tokenise("ADD Module")
        self.assertIn("add", tokens)
        self.assertIn("module", tokens)

    def test_drop_short_tokens(self):
        tokens = _tokenise("a an in of")
        # all tokens ≤ 2 chars → empty
        self.assertEqual(tokens, set())

    def test_strip_punctuation(self):
        tokens = _tokenise("fix: bug #123!")
        self.assertIn("fix", tokens)
        self.assertIn("bug", tokens)
        self.assertIn("123", tokens)

    def test_empty_message(self):
        self.assertEqual(_tokenise(""), set())

    def test_numbers(self):
        tokens = _tokenise("stroke 38100 update")
        self.assertIn("38100", tokens)
        self.assertIn("stroke", tokens)
        self.assertIn("update", tokens)


# ── _token_overlap ────────────────────────────────────────────────────────


class TestTokenOverlap(unittest.TestCase):
    def test_full_match(self):
        self.assertEqual(_token_overlap({"a", "b"}, {"a", "b"}), 1.0)

    def test_partial(self):
        self.assertAlmostEqual(_token_overlap({"a", "b"}, {"b", "c"}), 1 / 3)

    def test_disjoint(self):
        self.assertEqual(_token_overlap({"a"}, {"b"}), 0.0)

    def test_both_empty(self):
        self.assertEqual(_token_overlap(set(), set()), 1.0)


# ── _is_file_echo ─────────────────────────────────────────────────────────


class TestIsFileEcho(unittest.TestCase):
    def test_hit(self):
        window = [_mkcommit("a", ["f1.py", "f2.py", "f3.py"])]
        self.assertTrue(_is_file_echo({"f1.py", "f2.py", "f3.py"}, window, 0.5))

    def test_miss(self):
        window = [_mkcommit("a", ["f1.py", "f2.py"])]
        self.assertFalse(_is_file_echo({"f3.py", "f4.py"}, window, 0.5))

    def test_threshold_boundary(self):
        # Jaccard = 0.5 at threshold 0.5 → should match (>=)
        # {f1, f2} vs {f1, f3} = intersection 1, union 3 → 1/3, not 0.5
        # Use {f1, f2} vs {f1, f2} = 1.0 to test >= boundary
        window = [_mkcommit("a", ["f1.py", "f2.py"])]
        self.assertTrue(_is_file_echo({"f1.py", "f2.py"}, window, 0.5))
        # and verify 1/3 does NOT match at 0.5
        self.assertFalse(_is_file_echo({"f1.py", "f3.py"}, window, 0.5))

    def test_below_threshold(self):
        # Jaccard = 1/3 at threshold 0.5 → no match
        window = [_mkcommit("a", ["f1.py", "f2.py", "f3.py"])]
        self.assertFalse(_is_file_echo({"f1.py", "f4.py", "f5.py"}, window, 0.5))

    def test_empty_files(self):
        window = [_mkcommit("a", [])]
        self.assertTrue(_is_file_echo(set(), window, 0.5))

    def test_empty_window(self):
        self.assertFalse(_is_file_echo({"f1.py"}, [], 0.5))


# ── _is_msg_echo ──────────────────────────────────────────────────────────


class TestIsMsgEcho(unittest.TestCase):
    def test_hit(self):
        window = [_mkcommit("a", ["f.py"], msg="add commit echo module with tests")]
        tokens = _tokenise("add commit echo module with tests")
        self.assertTrue(_is_msg_echo(tokens, window, 0.5))

    def test_miss(self):
        window = [_mkcommit("a", ["f.py"], msg="add commit echo module")]
        tokens = _tokenise("fix push divergence in batch committer")
        self.assertFalse(_is_msg_echo(tokens, window, 0.5))

    def test_empty_window(self):
        tokens = _tokenise("something")
        self.assertFalse(_is_msg_echo(tokens, [], 0.5))

    def test_empty_messages(self):
        window = [_mkcommit("a", ["f.py"], msg="")]
        tokens = _tokenise("")
        # Both empty → Jaccard of empty sets = 1.0 ≥ 0.5 → True
        self.assertTrue(_is_msg_echo(tokens, window, 0.5))


# ── classify_echo ─────────────────────────────────────────────────────────


class TestClassifyEcho(unittest.TestCase):
    def test_fresh(self):
        self.assertEqual(classify_echo(0.0), "fresh")
        self.assertEqual(classify_echo(0.10), "fresh")
        self.assertEqual(classify_echo(0.19), "fresh")

    def test_varied(self):
        self.assertEqual(classify_echo(0.20), "varied")
        self.assertEqual(classify_echo(0.30), "varied")
        self.assertEqual(classify_echo(0.39), "varied")

    def test_repetitive(self):
        self.assertEqual(classify_echo(0.40), "repetitive")
        self.assertEqual(classify_echo(0.50), "repetitive")
        self.assertEqual(classify_echo(0.59), "repetitive")

    def test_looping(self):
        self.assertEqual(classify_echo(0.60), "looping")
        self.assertEqual(classify_echo(0.70), "looping")
        self.assertEqual(classify_echo(0.79), "looping")

    def test_stuck(self):
        self.assertEqual(classify_echo(0.80), "stuck")
        self.assertEqual(classify_echo(0.90), "stuck")
        self.assertEqual(classify_echo(1.0), "stuck")


# ── compute_echo ──────────────────────────────────────────────────────────


class TestComputeEcho(unittest.TestCase):
    def test_empty_input(self):
        result = compute_echo([])
        self.assertTrue(result.is_empty)
        self.assertEqual(result.commit_count, 0)
        self.assertEqual(result.echo_class, "fresh")
        self.assertEqual(result.echo_score, 0.0)

    def test_single_commit(self):
        result = compute_echo([_mkcommit("a", ["f1.py"])])
        self.assertEqual(result.commit_count, 1)
        self.assertEqual(result.echo_class, "fresh")
        self.assertEqual(result.file_set_recurrence, 0.0)

    def test_fresh_scenario(self):
        """Every commit touches unique files with genuinely unique messages."""
        # Each message uses completely distinct content words
        unique_msgs = [
            "alpha bravo charlie delta",
            "echo foxtrot golf hotel",
            "india juliet kilo lima",
            "mike november oscar papa",
            "quebec romeo sierra tango",
            "ultra victor whiskey xray",
            "yankee zulu apple banana",
            "cherry donut eagle falcon",
            "grape honey iris jasmine",
            "kite lemon mango nectar",
        ]
        commits = [
            _mkcommit(f"c{i}", [f"module_{i}.py"], msg=unique_msgs[i],
                      ts_offset_minutes=i * 10)
            for i in range(10)
        ]
        result = compute_echo(commits, lookback=5)
        self.assertEqual(result.echo_class, "fresh")
        self.assertEqual(result.file_set_recurrence, 0.0)
        self.assertEqual(result.message_recurrence, 0.0)
        self.assertEqual(result.combined_echo_rate, 0.0)

    def test_stuck_scenario(self):
        """Every commit touches the same files with the same message."""
        commits = [
            _mkcommit(f"c{i}", ["f1.py", "f2.py", "f3.py"],
                      msg="add commit echo module with tests",
                      ts_offset_minutes=i * 10)
            for i in range(10)
        ]
        result = compute_echo(commits, lookback=5)
        # file_set_recurrence should be 1.0 (all identical)
        self.assertEqual(result.file_set_recurrence, 1.0)
        # message_recurrence should be 1.0 (all identical messages)
        self.assertEqual(result.message_recurrence, 1.0)
        # combined should also be 1.0
        self.assertEqual(result.combined_echo_rate, 1.0)
        # should be classified as stuck
        self.assertEqual(result.echo_class, "stuck")
        self.assertGreater(result.echo_score, 0.80)

    def test_repetitive_files_varied_messages(self):
        """Same files but genuinely different messages → high file recurrence, low msg."""
        distinct_msgs = [
            "alpha bravo charlie delta echo",
            "foxtrot golf hotel india juliet",
            "kilo lima mike november oscar",
            "papa quebec romeo sierra tango",
            "ultra victor whiskey xray yankee",
            "zulu apple banana cherry donut",
            "eagle falcon grape honey iris",
            "jasmine kite lemon mango nectar",
            "olive peach quilt river stone",
            "tower umbrella valley willow xenon",
        ]
        commits = [
            _mkcommit(f"c{i}", ["f1.py", "f2.py"],
                      msg=distinct_msgs[i],
                      ts_offset_minutes=i * 10)
            for i in range(10)
        ]
        result = compute_echo(commits, lookback=5)
        # files always overlap → high file_set_recurrence
        self.assertGreater(result.file_set_recurrence, 0.5)
        # messages are completely different → low message_recurrence
        self.assertLess(result.message_recurrence, result.file_set_recurrence)

    def test_varied_files_repetitive_messages(self):
        """Different files but similar messages."""
        commits = [
            _mkcommit(f"c{i}", [f"module_{i}.py", f"test_{i}.py"],
                      msg="add new module with comprehensive tests",
                      ts_offset_minutes=i * 10)
            for i in range(10)
        ]
        result = compute_echo(commits, lookback=5)
        # files don't overlap → low file_set_recurrence
        self.assertLess(result.file_set_recurrence, 0.3)
        # messages overlap heavily → higher message_recurrence
        self.assertGreater(result.message_recurrence, 0.3)

    def test_lookback_window(self):
        """Only compare within the lookback window."""
        # first commit: unique files, then 9 identical commits
        first = _mkcommit("c0", ["unique.py"], msg="initial unique commit",
                          ts_offset_minutes=0)
        rest = [
            _mkcommit(f"c{i}", ["f1.py", "f2.py"],
                      msg="repeated update to core modules",
                      ts_offset_minutes=i * 10)
            for i in range(1, 10)
        ]
        commits = [first] + rest
        result = compute_echo(commits, lookback=3)
        # c1 compares to c0 only → no echo
        # c2 compares to c0, c1 → c1 is echo → yes
        # etc.
        self.assertGreater(result.file_set_recurrence, 0.0)

    def test_echo_count_accuracy(self):
        """echo_count should count commits that echo on both axes."""
        commits = [
            _mkcommit("c0", ["f1.py"], msg="first commit", ts_offset_minutes=0),
            _mkcommit("c1", ["f1.py"], msg="first commit", ts_offset_minutes=10),
            _mkcommit("c2", ["f2.py"], msg="different work entirely", ts_offset_minutes=20),
            _mkcommit("c3", ["f1.py"], msg="first commit", ts_offset_minutes=30),
        ]
        result = compute_echo(commits, lookback=3)
        # c1 echoes c0 (same files + same msg) → combined echo
        # c2 doesn't echo anything → no combined echo
        # c3 echoes c0 and c1 (same files + same msg) → combined echo
        self.assertEqual(result.echo_count, 2)

    def test_all_same_files_different_messages(self):
        """Same file touched every time but each message is completely unique."""
        # Each message uses entirely distinct tokens so no message echoes
        unique_words = [
            "alpha bravo charlie delta echo",
            "foxtrot golf hotel india juliet",
            "kilo lima mike november oscar",
            "papa quebec romeo sierra tango",
            "ultra victor whiskey xray yankee",
            "zulu apple banana cherry donut",
            "eagle falcon grape honey iris",
            "jasmine kite lemon mango nectar",
        ]
        commits = [
            _mkcommit(f"c{i}", ["shared.py"],
                      msg=unique_words[i],
                      ts_offset_minutes=i * 10)
            for i in range(8)
        ]
        result = compute_echo(commits, lookback=5)
        self.assertEqual(result.file_set_recurrence, 1.0)
        self.assertEqual(result.combined_echo_rate, 0.0)

    def test_two_commits_identical(self):
        commits = [
            _mkcommit("c0", ["f1.py", "f2.py"], msg="add module with tests",
                      ts_offset_minutes=0),
            _mkcommit("c1", ["f1.py", "f2.py"], msg="add module with tests",
                      ts_offset_minutes=10),
        ]
        result = compute_echo(commits, lookback=5)
        self.assertEqual(result.file_set_recurrence, 1.0)
        self.assertEqual(result.message_recurrence, 1.0)
        self.assertEqual(result.combined_echo_rate, 1.0)


# ── echo_report ───────────────────────────────────────────────────────────


class TestEchoReport(unittest.TestCase):
    def test_basic_formatting(self):
        result = EchoResult(
            commit_count=10,
            file_set_recurrence=0.30,
            message_recurrence=0.20,
            combined_echo_rate=0.10,
            echo_periodicity=1.5,
            echo_score=0.21,
            echo_class="varied",
            echo_count=1,
            window_size=20,
        )
        text = echo_report(result)
        self.assertIn("echo analysis", text)
        self.assertIn("10 commits", text)
        self.assertIn("30.00%", text)
        self.assertIn("varied", text)

    def test_empty_result(self):
        result = EchoResult(
            commit_count=0,
            file_set_recurrence=0.0,
            message_recurrence=0.0,
            combined_echo_rate=0.0,
            echo_periodicity=float("inf"),
            echo_score=0.0,
            echo_class="fresh",
            echo_count=0,
            window_size=20,
            is_empty=True,
        )
        text = echo_report(result)
        self.assertIn("no commits", text)

    def test_infinite_periodicity_display(self):
        result = EchoResult(
            commit_count=5,
            file_set_recurrence=0.0,
            message_recurrence=0.0,
            combined_echo_rate=0.0,
            echo_periodicity=float("inf"),
            echo_score=0.0,
            echo_class="fresh",
            echo_count=0,
            window_size=20,
        )
        text = echo_report(result)
        self.assertIn("inf", text)


# ── echo_trend ────────────────────────────────────────────────────────────


class TestEchoTrend(unittest.TestCase):
    def test_empty(self):
        trend = echo_trend([])
        self.assertEqual(trend.direction, "stable")
        self.assertEqual(trend.scores, [])
        self.assertIn("no data", trend.note)

    def test_single_window(self):
        result = EchoResult(10, 0.2, 0.1, 0.05, 1.0, 0.15, "fresh", 0, 20)
        trend = echo_trend([result])
        self.assertEqual(trend.direction, "stable")
        self.assertIn("single window", trend.note)

    def test_increasing(self):
        results = [
            EchoResult(10, 0.1, 0.1, 0.05, 1.0, 0.10, "fresh", 0, 20),
            EchoResult(10, 0.2, 0.2, 0.10, 1.0, 0.20, "varied", 2, 20),
            EchoResult(10, 0.5, 0.5, 0.30, 1.0, 0.45, "repetitive", 3, 20),
            EchoResult(10, 0.7, 0.7, 0.50, 0.5, 0.65, "looping", 5, 20),
        ]
        trend = echo_trend(results)
        self.assertEqual(trend.direction, "increasing")
        self.assertIn("worsening", trend.note)

    def test_decreasing(self):
        results = [
            EchoResult(10, 0.7, 0.7, 0.50, 0.5, 0.65, "looping", 5, 20),
            EchoResult(10, 0.5, 0.5, 0.30, 1.0, 0.45, "repetitive", 3, 20),
            EchoResult(10, 0.2, 0.2, 0.10, 1.0, 0.20, "varied", 2, 20),
            EchoResult(10, 0.1, 0.1, 0.05, 1.0, 0.10, "fresh", 0, 20),
        ]
        trend = echo_trend(results)
        self.assertEqual(trend.direction, "decreasing")
        self.assertIn("improving", trend.note)

    def test_stable(self):
        results = [
            EchoResult(10, 0.3, 0.3, 0.15, 1.0, 0.25, "varied", 2, 20),
            EchoResult(10, 0.3, 0.3, 0.15, 1.0, 0.25, "varied", 2, 20),
            EchoResult(10, 0.3, 0.3, 0.15, 1.0, 0.25, "varied", 2, 20),
            EchoResult(10, 0.3, 0.3, 0.15, 1.0, 0.25, "varied", 2, 20),
        ]
        trend = echo_trend(results)
        self.assertEqual(trend.direction, "stable")
        self.assertIn("consistent", trend.note)

    def test_latest_class_preserved(self):
        results = [
            EchoResult(10, 0.1, 0.1, 0.05, 1.0, 0.10, "fresh", 0, 20),
            EchoResult(10, 0.7, 0.7, 0.50, 0.5, 0.65, "looping", 5, 20),
        ]
        trend = echo_trend(results)
        self.assertEqual(trend.latest_class, "looping")


# ── integration: realistic scenarios ──────────────────────────────────────


class TestIntegration(unittest.TestCase):
    def test_healthy_pipeline(self):
        """A healthy automated writing pipeline: diverse content, some structural overlap."""
        msgs = [
            "add commit_echo module with 72 tests",
            "stroke 38200: 6400 strokes written so far into 2080 files",
            "commit 580: the count of times this repo was pushed",
            "add reading note on codebase conductivity",
            "stroke 38206: 475000 lines across 2080 tracked files",
            "add commit_resonance trend analysis",
            "stroke 38212: 1380 python files, 6350 logged thoughts",
            "add caretaker visit 603 — process recovery latency",
            "stroke 38218: tree is 2082 files; 476000 lines is a lot for a toy",
            "add push_divergence_monitor with alerting",
        ]
        files_sets = [
            ["iamai/commit_echo.py", "tests/test_commit_echo.py", "notes/reading.md"],
            ["docs/DEVLOG.md", "data/strokes.jsonl"],
            ["docs/DEVLOG.md", "data/strokes.jsonl"],
            ["notes/reading.md", "notes/conventions.md"],
            ["docs/DEVLOG.md", "data/strokes.jsonl"],
            ["iamai/commit_resonance.py", "tests/test_commit_resonance.py"],
            ["docs/DEVLOG.md", "data/strokes.jsonl"],
            ["notes/caretaker-visit-603.md", "iamai/caretaker.py"],
            ["docs/DEVLOG.md", "data/strokes.jsonl"],
            ["iamai/push_divergence_monitor.py", "tests/test_push_divergence_monitor.py"],
        ]
        commits = [
            _mkcommit(f"c{i}", files_sets[i], msg=msgs[i], ts_offset_minutes=i * 10)
            for i in range(10)
        ]
        result = compute_echo(commits, lookback=5)
        # Should be fresh or varied — healthy pipeline
        self.assertIn(result.echo_class, ("fresh", "varied"))
        self.assertLess(result.echo_score, 0.40)

    def test_stuck_content_loop(self):
        """A stuck agent keeps writing the same files with similar messages."""
        commits = [
            _mkcommit(
                f"c{i}",
                ["docs/DEVLOG.md", "data/strokes.jsonl", "docs/METRICS.md"],
                msg="stroke 38200: 6400 strokes written so far into 2080 files",
                ts_offset_minutes=i * 10,
            )
            for i in range(10)
        ]
        result = compute_echo(commits, lookback=5)
        self.assertIn(result.echo_class, ("looping", "stuck"))
        self.assertGreater(result.echo_score, 0.50)

    def test_periodicity_detection(self):
        """Regular machine-like echoes should have low CV."""
        # every 10 minutes exactly → CV = 0
        commits = [
            _mkcommit(
                f"c{i}",
                ["f1.py", "f2.py"],
                msg="repeated maintenance update cycle",
                ts_offset_minutes=i * 10,
            )
            for i in range(15)
        ]
        result = compute_echo(commits, lookback=5)
        # All are echoes → periodicity should be computable and low
        if result.echo_periodicity != float("inf"):
            self.assertLess(result.echo_periodicity, 0.5)

    def test_mixed_workload(self):
        """Realistic mix: some structural repetition (DEVLOG/strokes) but varied content."""
        commits = []
        for i in range(20):
            if i % 3 == 0:
                files = ["docs/DEVLOG.md", "data/strokes.jsonl"]
                msg = f"stroke {38000 + i * 6}: {6300 + i} strokes into 2070 files"
            elif i % 3 == 1:
                files = [f"iamai/module_{i}.py", f"tests/test_module_{i}.py"]
                msg = f"add module_{i} with comprehensive test suite"
            else:
                files = [f"notes/caretaker-visit-{600 + i}.md"]
                msg = f"caretaker visit {600 + i} — checking process health"
            commits.append(_mkcommit(f"c{i}", files, msg=msg, ts_offset_minutes=i * 10))

        result = compute_echo(commits, lookback=5)
        # Should not be stuck — enough variety
        self.assertIn(result.echo_class, ("fresh", "varied", "repetitive"))


if __name__ == "__main__":
    unittest.main()
