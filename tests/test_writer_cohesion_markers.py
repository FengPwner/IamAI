#!/usr/bin/env python3
"""Tests for iamai.writer_cohesion_markers — discourse connective analysis."""

import json
import math
import os
import sys
import tempfile
import textwrap

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_cohesion_markers import (
    _classify,
    _empty_result,
    _find_markers,
    _shannon_entropy,
    _split_sentences,
    compute_cohesion,
    cohesion_report,
    cohesion_summary,
    main,
)


# =========================================================================
# _split_sentences
# =========================================================================

class TestSplitSentences:
    def test_basic(self):
        sents = _split_sentences("Hello world. How are you? Fine.")
        assert len(sents) == 3

    def test_empty(self):
        assert _split_sentences("") == []

    def test_whitespace_only(self):
        assert _split_sentences("   \n  ") == []

    def test_no_punctuation(self):
        sents = _split_sentences("just a fragment")
        assert len(sents) == 1
        assert sents[0] == "just a fragment"

    def test_exclamation(self):
        sents = _split_sentences("Wow! Really! Yes.")
        assert len(sents) == 3

    def test_newline_split(self):
        text = "First line.\nSecond line."
        sents = _split_sentences(text)
        assert len(sents) == 2


# =========================================================================
# _find_markers
# =========================================================================

class TestFindMarkers:
    def test_additive(self):
        markers = _find_markers("Furthermore, we should consider this.")
        cats = [m[0] for m in markers]
        assert "additive" in cats

    def test_adversative(self):
        markers = _find_markers("However, the results were inconclusive.")
        cats = [m[0] for m in markers]
        assert "adversative" in cats

    def test_causal(self):
        markers = _find_markers("Therefore, we conclude the experiment failed.")
        cats = [m[0] for m in markers]
        assert "causal" in cats

    def test_temporal(self):
        markers = _find_markers("Then we moved to the next phase.")
        cats = [m[0] for m in markers]
        assert "temporal" in cats

    def test_conditional(self):
        markers = _find_markers("If the test passes, we deploy.")
        cats = [m[0] for m in markers]
        assert "conditional" in cats

    def test_multiple_markers(self):
        markers = _find_markers("However, since the data was lost, therefore we restart.")
        cats = [m[0] for m in markers]
        assert "adversative" in cats
        assert "causal" in cats

    def test_no_markers(self):
        markers = _find_markers("The cat sat on the mat.")
        assert markers == []

    def test_case_insensitive(self):
        markers = _find_markers("HOWEVER, this is fine.")
        assert len(markers) >= 1

    def test_canonical_names(self):
        markers = _find_markers("Moreover, also we need this.")
        names = [m[1] for m in markers]
        assert "moreover" in names
        assert "also" in names


# =========================================================================
# Additive pattern coverage
# =========================================================================

class TestAdditivePatterns:
    def test_also(self):
        assert any(m[1] == "also" for m in _find_markers("We also need this."))

    def test_furthermore(self):
        assert any(m[1] == "furthermore" for m in _find_markers("Furthermore, yes."))

    def test_moreover(self):
        assert any(m[1] == "moreover" for m in _find_markers("Moreover, it works."))

    def test_in_addition(self):
        assert any(m[1] == "in addition" for m in _find_markers("In addition, we tested."))

    def test_besides(self):
        assert any(m[1] == "besides" for m in _find_markers("Besides, it is cheap."))

    def test_similarly(self):
        assert any(m[1] == "similarly" for m in _find_markers("Similarly, the other case."))

    def test_likewise(self):
        assert any(m[1] == "likewise" for m in _find_markers("Likewise, they agreed."))

    def test_not_only(self):
        assert any(m[1] == "not only" for m in _find_markers("Not only fast but also cheap."))

    def test_as_well_as(self):
        assert any(m[1] == "as well as" for m in _find_markers("This as well as that."))


# =========================================================================
# Adversative pattern coverage
# =========================================================================

class TestAdversativePatterns:
    def test_however(self):
        assert any(m[1] == "however" for m in _find_markers("However, no."))

    def test_nevertheless(self):
        assert any(m[1] == "nevertheless" for m in _find_markers("Nevertheless, we tried."))

    def test_nonetheless(self):
        assert any(m[1] == "nonetheless" for m in _find_markers("Nonetheless, it held."))

    def test_yet(self):
        assert any(m[1] == "yet" for m in _find_markers("Yet we persisted."))

    def test_on_the_other_hand(self):
        assert any(m[1] == "on the other hand"
                    for m in _find_markers("On the other hand, maybe not."))

    def test_conversely(self):
        assert any(m[1] == "conversely" for m in _find_markers("Conversely, less is more."))

    def test_in_contrast(self):
        assert any(m[1] == "in contrast"
                    for m in _find_markers("In contrast, the old way failed."))

    def test_despite(self):
        assert any(m[1] == "despite" for m in _find_markers("Despite the rain, we went."))

    def test_although(self):
        assert any(m[1] == "although" for m in _find_markers("Although tired, she ran."))

    def test_whereas(self):
        assert any(m[1] == "whereas" for m in _find_markers("He likes tea, whereas she prefers coffee."))


# =========================================================================
# Causal pattern coverage
# =========================================================================

class TestCausalPatterns:
    def test_therefore(self):
        assert any(m[1] == "therefore" for m in _find_markers("Therefore, we act."))

    def test_thus(self):
        assert any(m[1] == "thus" for m in _find_markers("Thus, it ends."))

    def test_hence(self):
        assert any(m[1] == "hence" for m in _find_markers("Hence the delay."))

    def test_consequently(self):
        assert any(m[1] == "consequently"
                    for m in _find_markers("Consequently, we lost data."))

    def test_as_a_result(self):
        assert any(m[1] == "as a result"
                    for m in _find_markers("As a result, nothing worked."))

    def test_because(self):
        assert any(m[1] == "because" for m in _find_markers("Because it rained."))

    def test_since(self):
        assert any(m[1] == "since" for m in _find_markers("Since we have time."))

    def test_accordingly(self):
        assert any(m[1] == "accordingly" for m in _find_markers("Accordingly, we adjusted."))

    def test_due_to(self):
        assert any(m[1] == "due to" for m in _find_markers("Due to the error."))


# =========================================================================
# Temporal pattern coverage
# =========================================================================

class TestTemporalPatterns:
    def test_then(self):
        assert any(m[1] == "then" for m in _find_markers("Then we left."))

    def test_next(self):
        assert any(m[1] == "next" for m in _find_markers("Next, we tested."))

    def test_meanwhile(self):
        assert any(m[1] == "meanwhile" for m in _find_markers("Meanwhile, they waited."))

    def test_subsequently(self):
        assert any(m[1] == "subsequently"
                    for m in _find_markers("Subsequently, we fixed it."))

    def test_finally(self):
        assert any(m[1] == "finally" for m in _find_markers("Finally, it worked."))

    def test_eventually(self):
        assert any(m[1] == "eventually"
                    for m in _find_markers("Eventually, the truth came out."))

    def test_previously(self):
        assert any(m[1] == "previously"
                    for m in _find_markers("Previously, we discussed this."))

    def test_first(self):
        assert any(m[1] == "first" for m in _find_markers("First, we prepare."))

    def test_lastly(self):
        assert any(m[1] == "lastly" for m in _find_markers("Lastly, we conclude."))


# =========================================================================
# Conditional pattern coverage
# =========================================================================

class TestConditionalPatterns:
    def test_if(self):
        assert any(m[1] == "if" for m in _find_markers("If it works, ship it."))

    def test_unless(self):
        assert any(m[1] == "unless" for m in _find_markers("Unless we fix it."))

    def test_whether(self):
        assert any(m[1] == "whether" for m in _find_markers("Whether it passes or not."))

    def test_provided_that(self):
        assert any(m[1] == "provided that"
                    for m in _find_markers("Provided that we have time."))

    def test_in_case(self):
        assert any(m[1] == "in case" for m in _find_markers("In case of emergency."))

    def test_even_if(self):
        assert any(m[1] == "even if" for m in _find_markers("Even if it fails, we learn."))


# =========================================================================
# _shannon_entropy
# =========================================================================

class TestShannonEntropy:
    def test_empty(self):
        assert _shannon_entropy({}) == 0.0

    def test_single_category(self):
        assert _shannon_entropy({"a": 10}) == 0.0

    def test_uniform_two(self):
        h = _shannon_entropy({"a": 5, "b": 5})
        assert abs(h - math.log(2)) < 1e-9

    def test_uniform_five(self):
        h = _shannon_entropy({"a": 2, "b": 2, "c": 2, "d": 2, "e": 2})
        assert abs(h - math.log(5)) < 1e-9

    def test_skewed(self):
        h = _shannon_entropy({"a": 97, "b": 1, "c": 1, "d": 1, "e": 0})
        assert 0 < h < math.log(5)


# =========================================================================
# _classify
# =========================================================================

class TestClassify:
    def test_absent(self):
        assert _classify(0.0, 0.0, 0.0, 0, []) == "absent"

    def test_sparse(self):
        assert _classify(0.1, 1.0, 0.5, 2, [0, 0, 0, 1, 0, 1]) == "sparse"

    def test_dense(self):
        # moderate diversity, no high CV
        counts = [2, 2, 2, 2, 1, 2, 2, 1, 2, 2]
        assert _classify(1.8, 1.2, 0.3, 18, counts) == "dense"

    def test_balanced(self):
        counts = [1, 1, 1, 0, 1, 1, 1, 0, 1, 1]
        assert _classify(0.8, 1.2, 0.25, 8, counts) == "balanced"

    def test_monotone(self):
        # dominance > 0.70 with total >= 3
        counts = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0]
        # dominance 0.5 — not enough for monotone via first check,
        # but density 0.2 is sparse; let's use a clearer case
        counts_mono = [1] * 10  # 10 sentences, 10 markers, all temporal
        assert _classify(1.0, 0.0, 1.0, 10, counts_mono) == "monotone"

    def test_erratic(self):
        # very high CV — some sentences have many markers, some none
        counts = [0, 0, 5, 0, 0, 5, 0, 0]
        result = _classify(1.25, 1.0, 0.5, 10, counts)
        assert result == "erratic"


# =========================================================================
# _empty_result
# =========================================================================

class TestEmptyResult:
    def test_structure(self):
        r = _empty_result()
        assert r["total_sentences"] == 0
        assert r["total_markers"] == 0
        assert r["marker_density"] == 0.0
        assert r["cohesion_label"] == "absent"
        assert r["dominant_category"] == "none"
        assert r["dominance_ratio"] == 0.0
        assert r["marker_richness"] == 0.0
        assert r["category_diversity"] == 0.0

    def test_all_keys_present(self):
        r = _empty_result()
        expected_keys = {
            "total_sentences", "total_markers", "marker_density",
            "additive_count", "adversative_count", "causal_count",
            "temporal_count", "conditional_count", "category_diversity",
            "dominant_category", "dominance_ratio", "marker_richness",
            "cohesion_label",
        }
        assert set(r.keys()) == expected_keys


# =========================================================================
# compute_cohesion — core analysis
# =========================================================================

class TestComputeCohesion:
    def test_empty(self):
        r = compute_cohesion("")
        assert r["cohesion_label"] == "absent"
        assert r["total_markers"] == 0

    def test_no_markers(self):
        r = compute_cohesion("The cat sat on the mat. The dog ran in the park.")
        assert r["total_markers"] == 0
        assert r["cohesion_label"] == "absent"

    def test_single_marker(self):
        r = compute_cohesion("However, the test passed. The code was clean.")
        assert r["total_markers"] >= 1
        assert r["adversative_count"] >= 1

    def test_mixed_categories(self):
        text = (
            "First, we prepared the data. "
            "However, the results were surprising. "
            "Therefore, we revised our hypothesis. "
            "Moreover, additional tests confirmed it. "
            "If the pattern holds, we can generalise."
        )
        r = compute_cohesion(text)
        assert r["temporal_count"] >= 1    # first
        assert r["adversative_count"] >= 1  # however
        assert r["causal_count"] >= 1       # therefore
        assert r["additive_count"] >= 1     # moreover
        assert r["conditional_count"] >= 1  # if
        assert r["category_diversity"] > 0

    def test_density_calculation(self):
        text = "However, it failed. Therefore, we fixed it. Moreover, we tested again."
        r = compute_cohesion(text)
        # 3 sentences, at least 3 markers → density >= 1.0
        assert r["total_sentences"] == 3
        assert r["marker_density"] >= 1.0

    def test_dominant_category(self):
        text = (
            "However, the test failed. "
            "However, the retry failed. "
            "However, we persisted."
        )
        r = compute_cohesion(text)
        assert r["dominant_category"] == "adversative"
        assert r["dominance_ratio"] >= 0.5

    def test_richness(self):
        # Use many different markers
        text = (
            "Furthermore, we started. "
            "However, problems arose. "
            "Therefore, we adapted. "
            "Meanwhile, others watched. "
            "If we succeed, we celebrate."
        )
        r = compute_cohesion(text)
        assert r["marker_richness"] > 0  # multiple unique markers

    def test_total_markers_is_sum(self):
        text = "However, therefore, moreover, then, if we try."
        r = compute_cohesion(text)
        assert r["total_markers"] == (
            r["additive_count"]
            + r["adversative_count"]
            + r["causal_count"]
            + r["temporal_count"]
            + r["conditional_count"]
        )

    def test_all_fields_present(self):
        r = compute_cohesion("However, it works. Therefore, we ship.")
        expected_keys = {
            "total_sentences", "total_markers", "marker_density",
            "additive_count", "adversative_count", "causal_count",
            "temporal_count", "conditional_count", "category_diversity",
            "dominant_category", "dominance_ratio", "marker_richness",
            "cohesion_label",
        }
        assert set(r.keys()) == expected_keys

    def test_non_negative_density(self):
        r = compute_cohesion("Some text here.")
        assert r["marker_density"] >= 0

    def test_unicode_text(self):
        r = compute_cohesion("However, the café was closed. Therefore, we walked home.")
        assert r["total_markers"] >= 2


# =========================================================================
# cohesion_report — on-disk integration
# =========================================================================

class TestCohesionReport:
    def test_with_strokes_file(self, tmp_path):
        strokes = tmp_path / "strokes.jsonl"
        records = [
            {"text": "However, the experiment failed."},
            {"text": "Therefore, we restarted the process."},
            {"text": "Moreover, we added more tests."},
        ]
        strokes.write_text("\n".join(json.dumps(r) for r in records))
        r = cohesion_report(str(strokes))
        assert r["total_markers"] >= 3
        assert r["adversative_count"] >= 1
        assert r["causal_count"] >= 1
        assert r["additive_count"] >= 1

    def test_missing_file(self, tmp_path):
        r = cohesion_report(str(tmp_path / "nonexistent.jsonl"))
        assert r["cohesion_label"] == "absent"

    def test_malformed_jsonl(self, tmp_path):
        strokes = tmp_path / "strokes.jsonl"
        strokes.write_text("not json\n{bad\n")
        r = cohesion_report(str(strokes))
        assert r["cohesion_label"] == "absent"

    def test_empty_text_fields(self, tmp_path):
        strokes = tmp_path / "strokes.jsonl"
        records = [
            {"text": ""},
            {"text": "   "},
            {"body": ""},
        ]
        strokes.write_text("\n".join(json.dumps(r) for r in records))
        r = cohesion_report(str(strokes))
        assert r["cohesion_label"] == "absent"

    def test_body_fallback(self, tmp_path):
        strokes = tmp_path / "strokes.jsonl"
        records = [{"body": "However, the body field works."}]
        strokes.write_text(json.dumps(records[0]))
        r = cohesion_report(str(strokes))
        assert r["total_markers"] >= 1


# =========================================================================
# cohesion_summary — formatting
# =========================================================================

class TestCohesionSummary:
    def test_line_count(self):
        r = compute_cohesion("However, it works. Therefore, we ship.")
        lines = cohesion_summary(r).split("\n")
        assert len(lines) == 12

    def test_key_fields_present(self):
        r = compute_cohesion("However, it works. Therefore, we ship.")
        s = cohesion_summary(r)
        assert "sentences:" in s
        assert "total markers:" in s
        assert "density:" in s
        assert "additive:" in s
        assert "adversative:" in s
        assert "causal:" in s
        assert "temporal:" in s
        assert "conditional:" in s
        assert "diversity" in s
        assert "dominant:" in s
        assert "richness:" in s
        assert "label:" in s


# =========================================================================
# CLI
# =========================================================================

class TestCLI:
    def test_default_output(self, capsys, tmp_path):
        strokes = tmp_path / "strokes.jsonl"
        records = [
            {"text": "However, we tried."},
            {"text": "Therefore, we succeeded."},
        ]
        strokes.write_text("\n".join(json.dumps(r) for r in records))
        rc = main(["--strokes", str(strokes)])
        assert rc == 0
        captured = capsys.readouterr()
        assert "label:" in captured.out

    def test_json_output(self, capsys, tmp_path):
        strokes = tmp_path / "strokes.jsonl"
        records = [{"text": "Moreover, the data was clean."}]
        strokes.write_text(json.dumps(records[0]))
        rc = main(["--strokes", str(strokes), "--json"])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "total_markers" in data
        assert "cohesion_label" in data

    def test_missing_file_json(self, capsys, tmp_path):
        rc = main(["--strokes", str(tmp_path / "nope.jsonl"), "--json"])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["cohesion_label"] == "absent"


# =========================================================================
# Edge cases
# =========================================================================

class TestEdgeCases:
    def test_single_sentence(self):
        r = compute_cohesion("However, this is just one sentence.")
        assert r["total_sentences"] == 1
        assert r["total_markers"] >= 1

    def test_very_long_text(self):
        sentences = ["However, sentence number %d is here." % i for i in range(200)]
        r = compute_cohesion(" ".join(sentences))
        assert r["total_sentences"] >= 100
        assert r["total_markers"] >= 100

    def test_repeated_same_marker(self):
        text = ". ".join(["However" for _ in range(20)]) + "."
        r = compute_cohesion(text)
        assert r["adversative_count"] >= 10
        assert r["dominance_ratio"] == 1.0

    def test_marker_in_middle_of_sentence(self):
        r = compute_cohesion("The results, however, were inconclusive.")
        assert r["adversative_count"] >= 1

    def test_multiple_markers_one_sentence(self):
        r = compute_cohesion("However, since it failed, therefore we restarted.")
        assert r["total_markers"] >= 3

    def test_alternating_categories(self):
        sentences = [
            "However, the first attempt failed.",
            "Therefore, we changed approach.",
            "Moreover, we added logging.",
            "Meanwhile, the team reviewed.",
            "If the fix holds, we deploy.",
        ]
        r = compute_cohesion(" ".join(sentences))
        assert r["category_diversity"] > 1.0  # good spread
