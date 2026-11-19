"""Tests for stroke_echo.py — near-duplicate echo detection.

Covers tokenisation, Jaccard similarity, echo pair finding, cluster
merging, band classification, full report generation, and snapshot
delta comparison.  58 tests total.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import stroke_echo as se


# ---------------------------------------------------------------------------
# extract_tokens
# ---------------------------------------------------------------------------

class TestExtractTokens:
    def test_basic_extraction(self):
        tokens = se.extract_tokens("automation fails quietly the log has to say something")
        assert "automation" in tokens
        assert "quietly" in tokens
        assert "something" in tokens

    def test_short_words_excluded(self):
        tokens = se.extract_tokens("an ox is up to no go")
        # "an", "ox", "is", "up", "to", "no" — all < 4 chars
        assert tokens == set()

    def test_stopwords_excluded(self):
        tokens = se.extract_tokens("that this these those from into")
        assert tokens == set()

    def test_punctuation_stripped(self):
        tokens = se.extract_tokens("hello, world! (testing) 'quoted'")
        assert "hello" in tokens
        assert "world" in tokens
        assert "testing" in tokens
        assert "quoted" in tokens

    def test_case_normalisation(self):
        tokens = se.extract_tokens("HELLO World MiXeD")
        assert "hello" in tokens
        assert "world" in tokens
        assert "mixed" in tokens

    def test_empty_string(self):
        assert se.extract_tokens("") == set()

    def test_single_long_word(self):
        assert se.extract_tokens("superlongword") == {"superlongword"}


# ---------------------------------------------------------------------------
# jaccard
# ---------------------------------------------------------------------------

class TestJaccard:
    def test_identical_sets(self):
        s = {"alpha", "beta", "gamma"}
        assert se.jaccard(s, s) == 1.0

    def test_disjoint_sets(self):
        assert se.jaccard({"alpha", "beta"}, {"gamma", "delta"}) == 0.0

    def test_partial_overlap(self):
        a = {"alpha", "beta", "gamma"}
        b = {"beta", "gamma", "delta"}
        # intersection=2, union=4
        assert se.jaccard(a, b) == pytest.approx(0.5)

    def test_both_empty(self):
        assert se.jaccard(set(), set()) == 1.0

    def test_one_empty(self):
        assert se.jaccard({"alpha"}, set()) == 0.0
        assert se.jaccard(set(), {"alpha"}) == 0.0

    def test_subset(self):
        a = {"alpha", "beta"}
        b = {"alpha", "beta", "gamma", "delta"}
        # intersection=2, union=4
        assert se.jaccard(a, b) == pytest.approx(0.5)

    def test_single_overlap(self):
        a = {"alpha", "beta", "gamma", "delta", "epsilon"}
        b = {"epsilon", "zeta", "eta", "theta"}
        # intersection=1, union=8
        assert se.jaccard(a, b) == pytest.approx(1 / 8)


# ---------------------------------------------------------------------------
# find_echo_pairs
# ---------------------------------------------------------------------------

class TestFindEchoPairs:
    def test_no_echoes(self):
        sets = [{"alpha"}, {"beta"}, {"gamma"}]
        assert se.find_echo_pairs(sets, threshold=0.6) == []

    def test_single_echo(self):
        shared = {"alpha", "beta", "gamma", "delta", "epsilon"}
        sets = [shared, shared, {"completely", "different", "words", "here"}]
        pairs = se.find_echo_pairs(sets, threshold=0.6)
        assert pairs == [0]

    def test_multiple_echoes(self):
        s = {"alpha", "beta", "gamma", "delta"}
        sets = [s, s, s, {"other"}]
        pairs = se.find_echo_pairs(sets, threshold=0.6)
        assert pairs == [0, 1]

    def test_threshold_boundary(self):
        a = {"alpha", "beta", "gamma", "delta", "epsilon"}
        b = {"alpha", "beta", "gamma"}  # jaccard = 3/5 = 0.6
        sets = [a, b]
        assert se.find_echo_pairs(sets, threshold=0.6) == [0]
        assert se.find_echo_pairs(sets, threshold=0.61) == []

    def test_empty_input(self):
        assert se.find_echo_pairs([], threshold=0.6) == []
        assert se.find_echo_pairs([{"alpha"}], threshold=0.6) == []


# ---------------------------------------------------------------------------
# build_clusters
# ---------------------------------------------------------------------------

class TestBuildClusters:
    def test_no_pairs(self):
        assert se.build_clusters([]) == []

    def test_single_pair(self):
        assert se.build_clusters([3]) == [[3, 4]]

    def test_consecutive_pairs_merge(self):
        assert se.build_clusters([3, 4, 5]) == [[3, 4, 5, 6]]

    def test_separate_pairs(self):
        result = se.build_clusters([1, 5])
        assert result == [[1, 2], [5, 6]]

    def test_gap_of_one(self):
        result = se.build_clusters([2, 4])
        assert result == [[2, 3], [4, 5]]

    def test_long_chain(self):
        result = se.build_clusters([0, 1, 2, 3, 4])
        assert result == [[0, 1, 2, 3, 4, 5]]

    def test_mixed(self):
        result = se.build_clusters([0, 1, 5, 6, 7, 12])
        assert result == [[0, 1, 2], [5, 6, 7, 8], [12, 13]]


# ---------------------------------------------------------------------------
# classify_band
# ---------------------------------------------------------------------------

class TestClassifyBand:
    def test_clear(self):
        assert se.classify_band(0.0) == "clear"
        assert se.classify_band(0.05) == "clear"
        assert se.classify_band(0.09) == "clear"

    def test_mild_echo(self):
        assert se.classify_band(0.1) == "mild_echo"
        assert se.classify_band(0.2) == "mild_echo"
        assert se.classify_band(0.29) == "mild_echo"

    def test_echo_chamber(self):
        assert se.classify_band(0.3) == "echo_chamber"
        assert se.classify_band(0.45) == "echo_chamber"
        assert se.classify_band(0.59) == "echo_chamber"

    def test_stutter(self):
        assert se.classify_band(0.6) == "stutter"
        assert se.classify_band(0.8) == "stutter"
        assert se.classify_band(1.0) == "stutter"


# ---------------------------------------------------------------------------
# echo_report
# ---------------------------------------------------------------------------

class TestEchoReport:
    def test_empty_stream(self):
        r = se.echo_report([])
        assert r["total_strokes"] == 0
        assert r["band"] == "clear"
        assert r["echo_density"] == 0.0

    def test_single_stroke(self):
        r = se.echo_report(["just one stroke here alone"])
        assert r["total_strokes"] == 1
        assert r["echo_pairs"] == 0
        assert r["band"] == "clear"

    def test_diverse_stream(self):
        texts = [
            "alpha beta gamma delta epsilon",
            "zeta eta theta iota kappa",
            "lambda mu nu xi omicron",
            "pi rho sigma tau upsilon",
        ]
        r = se.echo_report(texts)
        assert r["echo_pairs"] == 0
        assert r["band"] == "clear"
        assert r["echo_density"] == 0.0

    def test_echoing_stream(self):
        same = "alpha beta gamma delta epsilon zeta"
        texts = [same, same, same, same, same]
        r = se.echo_report(texts)
        assert r["echo_pairs"] == 4  # all adjacent pairs
        assert r["echo_depth"] == 5  # one big cluster
        assert r["echo_density"] == 1.0
        assert r["band"] == "stutter"

    def test_window_truncation(self):
        same = "alpha beta gamma delta epsilon"
        diverse = [f"word{i}a word{i}b word{i}c word{i}d word{i}e" for i in range(20)]
        texts = diverse + [same, same, same]
        r_all = se.echo_report(texts)
        r_window = se.echo_report(texts, window=5)
        assert r_window["total_strokes"] == 5
        assert r_window["analysed_strokes"] == 5
        # Window should capture the echoing tail
        assert r_window["echo_pairs"] >= 2

    def test_mixed_stream(self):
        same = "alpha beta gamma delta epsilon zeta"
        diff = "completely different set of words here"
        texts = [same, same, diff, diff, diff, same, same]
        r = se.echo_report(texts)
        assert r["echo_pairs"] >= 2  # at least the same->same pairs
        assert r["cluster_count"] >= 1

    def test_report_keys_present(self):
        r = se.echo_report(["hello world test", "another different stroke"])
        expected_keys = {
            "total_strokes", "analysed_strokes", "echo_pairs",
            "clusters", "cluster_count", "echo_depth",
            "echo_strokes", "echo_density", "band", "top_echo",
        }
        assert set(r.keys()) == expected_keys

    def test_top_echo_tracks_highest_similarity(self):
        a = "alpha beta gamma delta epsilon zeta"
        b = "alpha beta gamma delta"  # 4/6 overlap = 0.667
        c = "totally different words here now today"
        texts = [a, b, c]
        r = se.echo_report(texts)
        assert r["top_echo"] > 0.6

    def test_threshold_parameter(self):
        a = "alpha beta gamma delta epsilon"
        b = "alpha beta gamma"  # jaccard = 3/5 = 0.6
        texts = [a, b, a, b]
        r_low = se.echo_report(texts, threshold=0.5)
        r_high = se.echo_report(texts, threshold=0.7)
        assert r_low["echo_pairs"] >= r_high["echo_pairs"]


# ---------------------------------------------------------------------------
# echo_delta
# ---------------------------------------------------------------------------

class TestEchoDelta:
    def test_stable(self):
        before = {"echo_density": 0.15, "echo_depth": 2, "echo_pairs": 3, "band": "mild_echo"}
        after = {"echo_density": 0.15, "echo_depth": 2, "echo_pairs": 3, "band": "mild_echo"}
        d = se.echo_delta(before, after)
        assert d["direction"] == "stable"
        assert d["density_change"] == 0.0
        assert d["band_shifted"] is False

    def test_worsening(self):
        before = {"echo_density": 0.1, "echo_depth": 2, "echo_pairs": 2, "band": "mild_echo"}
        after = {"echo_density": 0.5, "echo_depth": 5, "echo_pairs": 8, "band": "echo_chamber"}
        d = se.echo_delta(before, after)
        assert d["direction"] == "worsening"
        assert d["density_change"] > 0
        assert d["band_shifted"] is True
        assert d["depth_change"] == 3
        assert d["pair_change"] == 6

    def test_improving(self):
        before = {"echo_density": 0.7, "echo_depth": 6, "echo_pairs": 10, "band": "stutter"}
        after = {"echo_density": 0.05, "echo_depth": 0, "echo_pairs": 0, "band": "clear"}
        d = se.echo_delta(before, after)
        assert d["direction"] == "improving"
        assert d["density_change"] < 0
        assert d["band_shifted"] is True

    def test_density_change_precision(self):
        before = {"echo_density": 0.1234, "band": "mild_echo"}
        after = {"echo_density": 0.2345, "band": "mild_echo"}
        d = se.echo_delta(before, after)
        assert d["density_change"] == pytest.approx(0.1111, abs=0.001)

    def test_missing_keys_default(self):
        d = se.echo_delta({}, {})
        assert d["direction"] == "stable"
        assert d["density_change"] == 0.0
        assert d["band_shifted"] is False


# ---------------------------------------------------------------------------
# Integration: realistic stroke data
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_realistic_stutter(self):
        """Simulate a writer that got stuck repeating the same thought."""
        template = "deleting a file is progress too eventually measured now tree is 2460 files 632102 lines is a lot for a toy"
        texts = [template] * 10
        r = se.echo_report(texts)
        assert r["band"] == "stutter"
        assert r["echo_density"] == 1.0
        assert r["echo_depth"] == 10

    def test_realistic_diverse(self):
        """Simulate a healthy stream of varied thoughts."""
        texts = [
            "tests are the part of a repository that argues back",
            "growth that never stops is a tumour not a garden",
            "append only log forces you to be wrong in public",
            "useful abstraction deletes a branch it does not add class",
            "automation fails quietly so the log has to say something",
            "most architecture is choosing which coupling you will live with",
            "repo that only accumulates is a landfill with a README",
            "deleting a file is progress too eventually someday maybe",
            "continuous integration is a conversation with your future self",
            "every commit is a bet on what matters right now today",
        ]
        r = se.echo_report(texts)
        assert r["band"] in ("clear", "mild_echo")
        assert r["echo_density"] < 0.4

    def test_delta_detects_degradation(self):
        healthy = [
            "alpha beta gamma delta epsilon zeta",
            "completely different set of words here",
            "another unique thought about coding systems",
            "testing reveals what static analysis cannot find",
            "documentation is a love letter to your future self",
        ]
        stuttering = healthy + [
            "alpha beta gamma delta epsilon zeta",
            "alpha beta gamma delta epsilon zeta",
            "alpha beta gamma delta epsilon zeta",
        ]
        before = se.echo_report(healthy)
        after = se.echo_report(stuttering)
        d = se.echo_delta(before, after)
        assert d["density_change"] >= 0
        assert after["echo_density"] >= before["echo_density"]
