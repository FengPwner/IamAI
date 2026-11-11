#!/usr/bin/env python3
"""Tests for writer_grounding_density — 62 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_grounding_density import (  # noqa: E402
    _classify_grounding,
    _classify_phase_arc,
    _compute_index,
    _compute_phase_scores,
    _count_code_refs,
    _count_entities,
    _count_numbers,
    _get_stroke_text,
    _has_claim_marker,
    _linear_slope,
    _tokenize,
    analyze_concrete_markers,
    analyze_evidence_pairing,
    analyze_specificity,
    compute_grounding_metrics,
    format_grounding_report,
    is_concrete_stroke,
)


# ---------------------------------------------------------------------------
# Helper: _tokenize
# ---------------------------------------------------------------------------

class TestTokenize(unittest.TestCase):
    """Test _tokenize helper."""

    def test_basic_sentence(self):
        self.assertEqual(_tokenize("Hello World"), ["hello", "world"])

    def test_empty_string(self):
        self.assertEqual(_tokenize(""), [])

    def test_punctuation_stripped(self):
        tokens = _tokenize("foo, bar! baz.")
        self.assertEqual(tokens, ["foo", "bar", "baz"])

    def test_numbers_included(self):
        tokens = _tokenize("stroke 42 done")
        self.assertIn("42", tokens)

    def test_mixed_case(self):
        self.assertEqual(_tokenize("UPPER lower"), ["upper", "lower"])


# ---------------------------------------------------------------------------
# Helper: _get_stroke_text
# ---------------------------------------------------------------------------

class TestGetStrokeText(unittest.TestCase):
    """Test _get_stroke_text helper."""

    def test_text_key(self):
        self.assertEqual(_get_stroke_text({"text": "hello"}), "hello")

    def test_content_key(self):
        self.assertEqual(_get_stroke_text({"content": "world"}), "world")

    def test_empty_dict(self):
        self.assertEqual(_get_stroke_text({}), "")

    def test_none_value(self):
        self.assertEqual(_get_stroke_text({"text": None}), "")

    def test_non_string_value(self):
        result = _get_stroke_text({"text": 42})
        self.assertEqual(result, "42")


# ---------------------------------------------------------------------------
# Helper: _count_numbers
# ---------------------------------------------------------------------------

class TestCountNumbers(unittest.TestCase):
    """Test _count_numbers helper."""

    def test_no_numbers(self):
        self.assertEqual(_count_numbers("hello world"), 0)

    def test_single_integer(self):
        self.assertEqual(_count_numbers("stroke 42"), 1)

    def test_float(self):
        self.assertEqual(_count_numbers("score is 0.85"), 1)

    def test_percentage(self):
        self.assertEqual(_count_numbers("bloom 100.0%"), 1)

    def test_multiple_numbers(self):
        self.assertEqual(_count_numbers("2099 files, 486450 lines"), 2)

    def test_unit_suffixed(self):
        self.assertEqual(_count_numbers("took 150ms and 2GB"), 2)

    def test_empty(self):
        self.assertEqual(_count_numbers(""), 0)


# ---------------------------------------------------------------------------
# Helper: _count_entities
# ---------------------------------------------------------------------------

class TestCountEntities(unittest.TestCase):
    """Test _count_entities helper."""

    def test_url(self):
        self.assertEqual(_count_entities("see https://example.com/path"), 1)

    def test_file_path(self):
        self.assertEqual(_count_entities("in /usr/local/bin/tool"), 1)

    def test_commit_hash(self):
        self.assertEqual(_count_entities("commit af8dbeb done"), 1)

    def test_version(self):
        self.assertEqual(_count_entities("running v3.7.1 now"), 1)

    def test_no_entities(self):
        self.assertEqual(_count_entities("hello world"), 0)

    def test_pid(self):
        self.assertEqual(_count_entities("writer pid 6538 up"), 1)

    def test_multiple(self):
        text = "commit af8dbeb in /repo/path at v1.2.3"
        self.assertEqual(_count_entities(text), 3)


# ---------------------------------------------------------------------------
# Helper: _count_code_refs
# ---------------------------------------------------------------------------

class TestCountCodeRefs(unittest.TestCase):
    """Test _count_code_refs helper."""

    def test_python_file(self):
        self.assertEqual(_count_code_refs("see writer_coherence.py"), 1)

    def test_markdown_file(self):
        self.assertEqual(_count_code_refs("check README.md"), 1)

    def test_function_def(self):
        self.assertEqual(_count_code_refs("def compute_metrics"), 1)

    def test_test_function(self):
        self.assertEqual(_count_code_refs("test_basic_sentence"), 1)

    def test_no_refs(self):
        self.assertEqual(_count_code_refs("just plain text"), 0)

    def test_inline_code(self):
        self.assertEqual(_count_code_refs("run `git status` now"), 1)


# ---------------------------------------------------------------------------
# Helper: _has_claim_marker
# ---------------------------------------------------------------------------

class TestHasClaimMarker(unittest.TestCase):
    """Test _has_claim_marker helper."""

    def test_has_claim(self):
        self.assertTrue(_has_claim_marker(["this", "is", "important"]))

    def test_no_claim(self):
        self.assertFalse(_has_claim_marker(["the", "cat", "sat"]))

    def test_empty(self):
        self.assertFalse(_has_claim_marker([]))

    def test_multiple_markers(self):
        self.assertTrue(_has_claim_marker(["significant", "and", "crucial"]))

    def test_should_marker(self):
        self.assertTrue(_has_claim_marker(["we", "should", "fix"]))


# ---------------------------------------------------------------------------
# analyze_concrete_markers
# ---------------------------------------------------------------------------

class TestAnalyzeConcreteMarkers(unittest.TestCase):
    """Test analyze_concrete_markers."""

    def test_empty_text(self):
        result = analyze_concrete_markers("")
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["numbers"], 0)

    def test_numbers_only(self):
        result = analyze_concrete_markers("stroke 42 took 150ms")
        self.assertEqual(result["numbers"], 2)
        self.assertGreaterEqual(result["total"], 2)

    def test_mixed_markers(self):
        text = "commit af8dbeb touched 2099 files in 150ms"
        result = analyze_concrete_markers(text)
        self.assertGreaterEqual(result["numbers"], 2)
        self.assertGreaterEqual(result["entities"], 1)
        self.assertGreaterEqual(result["total"], 3)

    def test_code_ref_text(self):
        text = "the function def compute_metrics in writer_coherence.py"
        result = analyze_concrete_markers(text)
        self.assertGreaterEqual(result["code_refs"], 1)

    def test_total_is_sum(self):
        text = "commit abc1234 took 50ms in /repo/data"
        result = analyze_concrete_markers(text)
        self.assertEqual(
            result["total"],
            result["numbers"] + result["entities"] + result["code_refs"],
        )


# ---------------------------------------------------------------------------
# analyze_specificity
# ---------------------------------------------------------------------------

class TestAnalyzeSpecificity(unittest.TestCase):
    """Test analyze_specificity."""

    def test_empty(self):
        self.assertEqual(analyze_specificity(""), 0.0)

    def test_no_specifics(self):
        text = "the important thing is that we should be effective"
        score = analyze_specificity(text)
        self.assertEqual(score, 0.0)

    def test_highly_specific(self):
        text = "commit af8dbeb pid 6538 2099 files 486450 lines 150ms"
        score = analyze_specificity(text)
        self.assertGreater(score, 0.0)

    def test_cap_at_ten(self):
        # Create text with absurd number density
        text = " ".join(str(i) for i in range(100))
        score = analyze_specificity(text)
        self.assertLessEqual(score, 10.0)

    def test_short_text_with_number(self):
        text = "42"
        score = analyze_specificity(text)
        # 1 marker in 1 word = 100 per 100 words, capped at 10
        self.assertEqual(score, 10.0)


# ---------------------------------------------------------------------------
# is_concrete_stroke
# ---------------------------------------------------------------------------

class TestIsConcreteStroke(unittest.TestCase):
    """Test is_concrete_stroke."""

    def test_concrete(self):
        self.assertTrue(is_concrete_stroke("commit af8dbeb touched 2099 files"))

    def test_abstract(self):
        self.assertFalse(is_concrete_stroke("the system is doing well"))

    def test_empty(self):
        self.assertFalse(is_concrete_stroke(""))

    def test_custom_threshold(self):
        text = "42 files"
        self.assertTrue(is_concrete_stroke(text, threshold=1))
        self.assertFalse(is_concrete_stroke(text, threshold=5))


# ---------------------------------------------------------------------------
# analyze_evidence_pairing
# ---------------------------------------------------------------------------

class TestAnalyzeEvidencePairing(unittest.TestCase):
    """Test analyze_evidence_pairing."""

    def test_empty_strokes(self):
        self.assertEqual(analyze_evidence_pairing([]), 0.0)

    def test_no_claims(self):
        strokes = [
            {"text": "the cat sat on the mat"},
            {"text": "a dog ran in the park"},
        ]
        self.assertEqual(analyze_evidence_pairing(strokes), 0.0)

    def test_paired_in_same_stroke(self):
        strokes = [
            {"text": "this is important: commit af8dbeb touched 2099 files"},
        ]
        result = analyze_evidence_pairing(strokes)
        self.assertEqual(result, 1.0)

    def test_paired_in_next_stroke(self):
        strokes = [
            {"text": "this is important and significant"},
            {"text": "commit af8dbeb touched 2099 files"},
        ]
        result = analyze_evidence_pairing(strokes)
        self.assertEqual(result, 1.0)

    def test_unpaired_claim(self):
        strokes = [
            {"text": "this is important and significant"},
            {"text": "the system works well overall"},
        ]
        result = analyze_evidence_pairing(strokes)
        self.assertEqual(result, 0.0)

    def test_mixed_pairing(self):
        strokes = [
            {"text": "important result: 42 tests passed"},
            {"text": "significant change detected"},
            {"text": "just filler text here"},
            {"text": "crucial update to version v3.7.1"},
        ]
        result = analyze_evidence_pairing(strokes)
        # Claims at indices 0 (self-paired), 1 (next has no concrete), 3 (self-paired)
        # So 2 out of 3 paired
        self.assertGreater(result, 0.5)

    def test_window_size_2(self):
        strokes = [
            {"text": "this is important"},
            {"text": "nothing concrete here"},
            {"text": "commit af8dbeb shows 2099 files"},
        ]
        result = analyze_evidence_pairing(strokes, pairing_window=2)
        self.assertEqual(result, 1.0)


# ---------------------------------------------------------------------------
# compute_grounding_metrics
# ---------------------------------------------------------------------------

class TestComputeGroundingMetrics(unittest.TestCase):
    """Test compute_grounding_metrics."""

    def test_empty(self):
        result = compute_grounding_metrics([])
        self.assertEqual(result["strokes_analyzed"], 0)
        self.assertEqual(result["grounding_class"], "unmoored")

    def test_single_concrete(self):
        strokes = [{"text": "commit af8dbeb touched 2099 files in 150ms"}]
        result = compute_grounding_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 1)
        self.assertEqual(result["concrete_ratio"], 1.0)

    def test_single_abstract(self):
        strokes = [{"text": "the system is doing well overall"}]
        result = compute_grounding_metrics(strokes)
        self.assertEqual(result["concrete_ratio"], 0.0)

    def test_mixed_session(self):
        strokes = [
            {"text": "important: commit af8dbeb touched 2099 files"},
            {"text": "the system shows significant progress overall"},
            {"text": "stroke 38337 took 150ms with pid 6538"},
            {"text": "we should improve the cadence detection"},
        ]
        result = compute_grounding_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 4)
        self.assertGreater(result["concrete_ratio"], 0.0)
        self.assertLess(result["concrete_ratio"], 1.0)
        self.assertIn(result["grounding_class"],
                       ["anchored", "substantiated", "illustrated", "unmoored"])

    def test_highly_grounded_session(self):
        strokes = [
            {"text": "commit af8dbeb at 23:01 touched 2099 files in 150ms"},
            {"text": "pid 6538 wrote 42 strokes in 600s interval"},
            {"text": "tree has 486450 lines across 2099 tracked files"},
            {"text": "commit 92ca2f7 added 83 tests in writer_coherence.py"},
            {"text": "v3.7.1 running on /usr/local/bin/python3"},
        ]
        result = compute_grounding_metrics(strokes)
        self.assertGreater(result["grounding_index"], 0.4)
        self.assertIn(result["grounding_class"], ["anchored", "substantiated"])

    def test_abstract_session(self):
        strokes = [
            {"text": "the important thing is that we should be effective"},
            {"text": "significant progress is crucial for success"},
            {"text": "we must demonstrate clear and obvious improvement"},
            {"text": "the system shows promising and valuable results"},
        ]
        result = compute_grounding_metrics(strokes)
        self.assertEqual(result["concrete_ratio"], 0.0)
        self.assertIn(result["grounding_class"], ["illustrated", "unmoored"])

    def test_result_keys(self):
        result = compute_grounding_metrics([{"text": "hello 42"}])
        expected_keys = {
            "strokes_analyzed", "concrete_ratio", "evidence_pairing",
            "specificity_mean", "specificity_trend", "grounding_index",
            "grounding_class", "phase_scores", "phase_arc",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_phase_scores_length(self):
        strokes = [{"text": f"stroke {i}"} for i in range(8)]
        result = compute_grounding_metrics(strokes)
        self.assertEqual(len(result["phase_scores"]), 4)

    def test_phase_arc_valid(self):
        strokes = [{"text": f"commit abc{i} took {i}ms"} for i in range(8)]
        result = compute_grounding_metrics(strokes)
        self.assertIn(result["phase_arc"],
                       ["deepening", "stable", "rising", "falling"])

    def test_specificity_trend_positive(self):
        # Start abstract, end concrete
        strokes = [
            {"text": "the system is good"},
            {"text": "things are important"},
            {"text": "commit abc1234 at 42ms"},
            {"text": "pid 9999 wrote 100 files in 200ms via v3.7.1"},
        ]
        result = compute_grounding_metrics(strokes)
        self.assertGreater(result["specificity_trend"], 0.0)

    def test_specificity_trend_negative(self):
        # Start concrete, end abstract
        strokes = [
            {"text": "commit abc1234 pid 9999 at 42ms via v3.7.1"},
            {"text": "2099 files and 486450 lines in 150ms"},
            {"text": "things are important overall"},
            {"text": "the system should be effective"},
        ]
        result = compute_grounding_metrics(strokes)
        self.assertLess(result["specificity_trend"], 0.0)

    def test_grounding_index_range(self):
        strokes = [
            {"text": "mixed content with 42 numbers"},
            {"text": "and some important claims"},
            {"text": "plus commit abc1234 evidence"},
        ]
        result = compute_grounding_metrics(strokes)
        self.assertGreaterEqual(result["grounding_index"], 0.0)
        self.assertLessEqual(result["grounding_index"], 1.0)


# ---------------------------------------------------------------------------
# _compute_index
# ---------------------------------------------------------------------------

class TestComputeIndex(unittest.TestCase):
    """Test _compute_index."""

    def test_all_zero(self):
        self.assertEqual(_compute_index(0.0, 0.0, 0.0), 0.0)

    def test_all_one(self):
        result = _compute_index(1.0, 1.0, 2.0)
        self.assertAlmostEqual(result, 1.0, places=2)

    def test_specificity_normalization_cap(self):
        # specificity > 2.0 should be treated as 1.0
        result = _compute_index(1.0, 1.0, 100.0)
        self.assertAlmostEqual(result, 1.0, places=2)

    def test_partial_scores(self):
        result = _compute_index(0.5, 0.5, 1.0)
        # 0.40*0.5 + 0.35*0.5 + 0.25*(1.0/2.0) = 0.2 + 0.175 + 0.125 = 0.5
        self.assertAlmostEqual(result, 0.5, places=2)


# ---------------------------------------------------------------------------
# _classify_grounding
# ---------------------------------------------------------------------------

class TestClassifyGrounding(unittest.TestCase):
    """Test _classify_grounding."""

    def test_anchored(self):
        self.assertEqual(_classify_grounding(0.55), "anchored")
        self.assertEqual(_classify_grounding(0.80), "anchored")

    def test_substantiated(self):
        self.assertEqual(_classify_grounding(0.40), "substantiated")
        self.assertEqual(_classify_grounding(0.54), "substantiated")

    def test_illustrated(self):
        self.assertEqual(_classify_grounding(0.25), "illustrated")
        self.assertEqual(_classify_grounding(0.39), "illustrated")

    def test_unmoored(self):
        self.assertEqual(_classify_grounding(0.0), "unmoored")
        self.assertEqual(_classify_grounding(0.24), "unmoored")

    def test_boundary(self):
        self.assertEqual(_classify_grounding(0.55), "anchored")
        self.assertEqual(_classify_grounding(0.40), "substantiated")
        self.assertEqual(_classify_grounding(0.25), "illustrated")


# ---------------------------------------------------------------------------
# _compute_phase_scores
# ---------------------------------------------------------------------------

class TestComputePhaseScores(unittest.TestCase):
    """Test _compute_phase_scores."""

    def test_empty(self):
        self.assertEqual(_compute_phase_scores([]), [0.0, 0.0, 0.0, 0.0])

    def test_single(self):
        scores = _compute_phase_scores(["commit abc1234 at 42ms"])
        self.assertEqual(len(scores), 4)
        self.assertGreater(scores[0], 0.0)
        self.assertEqual(scores[1], 0.0)

    def test_four_strokes(self):
        texts = [
            "commit abc1234",
            "the system is good",
            "important change in 42 files",
            "abstract thinking here",
        ]
        scores = _compute_phase_scores(texts)
        self.assertEqual(len(scores), 4)

    def test_eight_strokes_balanced(self):
        texts = [f"commit abc{i} took {i}ms" for i in range(8)]
        scores = _compute_phase_scores(texts)
        self.assertEqual(len(scores), 4)
        # All should be > 0 since all are concrete
        for s in scores:
            self.assertGreater(s, 0.0)


# ---------------------------------------------------------------------------
# _classify_phase_arc
# ---------------------------------------------------------------------------

class TestClassifyPhaseArc(unittest.TestCase):
    """Test _classify_phase_arc."""

    def test_deepening(self):
        self.assertEqual(_classify_phase_arc([0.2, 0.4, 0.5, 0.48]), "deepening")

    def test_rising(self):
        self.assertEqual(_classify_phase_arc([0.1, 0.1, 0.12, 0.25]), "rising")

    def test_falling(self):
        self.assertEqual(_classify_phase_arc([0.5, 0.4, 0.35, 0.3]), "falling")

    def test_stable(self):
        self.assertEqual(_classify_phase_arc([0.3, 0.3, 0.3, 0.3]), "stable")

    def test_equal(self):
        self.assertEqual(_classify_phase_arc([0.0, 0.0, 0.0, 0.0]), "stable")


# ---------------------------------------------------------------------------
# _linear_slope
# ---------------------------------------------------------------------------

class TestLinearSlope(unittest.TestCase):
    """Test _linear_slope."""

    def test_empty(self):
        self.assertEqual(_linear_slope([]), 0.0)

    def test_single(self):
        self.assertEqual(_linear_slope([5.0]), 0.0)

    def test_positive_slope(self):
        self.assertGreater(_linear_slope([1.0, 2.0, 3.0, 4.0]), 0.0)

    def test_negative_slope(self):
        self.assertLess(_linear_slope([4.0, 3.0, 2.0, 1.0]), 0.0)

    def test_flat(self):
        self.assertAlmostEqual(_linear_slope([5.0, 5.0, 5.0]), 0.0)

    def test_known_value(self):
        # slope of [0, 1, 2, 3] = 1.0
        self.assertAlmostEqual(_linear_slope([0.0, 1.0, 2.0, 3.0]), 1.0)


# ---------------------------------------------------------------------------
# format_grounding_report
# ---------------------------------------------------------------------------

class TestFormatGroundingReport(unittest.TestCase):
    """Test format_grounding_report."""

    def test_basic_report(self):
        metrics = {
            "strokes_analyzed": 10,
            "grounding_index": 0.45,
            "grounding_class": "substantiated",
            "concrete_ratio": 0.6,
            "evidence_pairing": 0.5,
            "specificity_mean": 1.2,
            "specificity_trend": 0.05,
            "phase_scores": [0.3, 0.4, 0.5, 0.5],
            "phase_arc": "deepening",
        }
        report = format_grounding_report(metrics)
        self.assertIn("writer grounding density", report)
        self.assertIn("substantiated", report)
        self.assertIn("deepening", report)
        self.assertIn("0.45", report)

    def test_unmoored_report(self):
        metrics = {
            "strokes_analyzed": 5,
            "grounding_index": 0.1,
            "grounding_class": "unmoored",
            "concrete_ratio": 0.0,
            "evidence_pairing": 0.0,
            "specificity_mean": 0.0,
            "specificity_trend": 0.0,
            "phase_scores": [0.0, 0.0, 0.0, 0.0],
            "phase_arc": "stable",
        }
        report = format_grounding_report(metrics)
        self.assertIn("unmoored", report)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):
    """Integration tests with realistic stroke sequences."""

    def test_typical_writer_session(self):
        """Simulate a typical autonomous writer session."""
        strokes = [
            {"text": "stroke 38337: round 38337 bloom 100.0% plants 146/384"},
            {"text": "the important thing about cadence is regularity"},
            {"text": "commit af8dbeb touched 2099 files in 150ms"},
            {"text": "significant improvement in coherence detection"},
            {"text": "pid 6538 wrote 42 strokes across 6 categories"},
            {"text": "we should improve the evidence pairing algorithm"},
        ]
        result = compute_grounding_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 6)
        self.assertGreater(result["concrete_ratio"], 0.0)
        self.assertIn(result["grounding_class"],
                       ["anchored", "substantiated", "illustrated"])

    def test_diary_strokes_are_grounded(self):
        """IamAI diary strokes typically contain measurements."""
        strokes = [
            {"text": "if a number in a diary is not measured, it is fiction -- "
                     "measured now: 484179 lines across 2095 tracked files, "
                     "593 commits deep"},
            {"text": "ten minutes is long enough to be honest and short "
                     "enough to be boring -- measured now: 1397 python files, "
                     "6380 logged thoughts"},
            {"text": "a deterministic garden beats a random one: it records "
                     "elapsed time -- measured now: 6379 strokes written so "
                     "far into 2097 files"},
        ]
        result = compute_grounding_metrics(strokes)
        self.assertEqual(result["concrete_ratio"], 1.0)
        self.assertGreater(result["grounding_index"], 0.4)

    def test_long_session_phases(self):
        """Test phase analysis with enough strokes for quartile computation."""
        strokes = []
        for i in range(20):
            if i < 5:
                # Q1: abstract framing (no numbers = no concrete markers)
                strokes.append({"text": "this is an important topic to consider"})
            elif i < 10:
                # Q2: evidence accumulation
                strokes.append({"text": f"commit abc{i:07d} at {i*10}ms"})
            elif i < 15:
                # Q3: more evidence
                strokes.append({"text": f"pid {i} wrote {i*5} files via v1.2.3"})
            else:
                # Q4: synthesis
                strokes.append({"text": f"the overall trend shows {i}% improvement"})
        result = compute_grounding_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 20)
        self.assertEqual(len(result["phase_scores"]), 4)
        # Q1 should have lower grounding than Q2-Q3
        self.assertLess(result["phase_scores"][0], result["phase_scores"][1])


if __name__ == "__main__":
    unittest.main()
