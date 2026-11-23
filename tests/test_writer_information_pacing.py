"""Tests for iamai.writer_information_pacing — vocabulary introduction pacing analysis."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from iamai.writer_information_pacing import (
    _classify_pacing,
    _entropy,
    _first_occurrence_positions,
    _heaps_alpha,
    _load_strokes,
    _mean,
    _sentence_novelty_rates,
    _split_sentences,
    _tokenize,
    compute_pacing,
    pacing_report,
    pacing_state,
    pacing_summary,
)

# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------


class TestMean:
    def test_empty(self):
        assert _mean([]) == 0.0

    def test_single(self):
        assert _mean([7.0]) == 7.0

    def test_multiple(self):
        assert _mean([1.0, 2.0, 3.0]) == pytest.approx(2.0)

    def test_negative(self):
        assert _mean([-2.0, 2.0]) == pytest.approx(0.0)


class TestEntropy:
    def test_empty(self):
        assert _entropy([]) == 0.0

    def test_uniform(self):
        # 4 bins each 0.25 → entropy = 2.0
        assert _entropy([0.25, 0.25, 0.25, 0.25]) == pytest.approx(2.0)

    def test_single_bin(self):
        assert _entropy([1.0]) == pytest.approx(0.0)

    def test_skewed(self):
        # Mostly in one bin
        ent = _entropy([0.9, 0.05, 0.05])
        assert ent < 1.0  # Low entropy

    def test_zero_values_ignored(self):
        assert _entropy([0.5, 0.0, 0.5]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_empty(self):
        assert _tokenize("") == []

    def test_stop_words_removed(self):
        tokens = _tokenize("the quick brown fox is a very fast animal")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "a" not in tokens
        assert "very" not in tokens

    def test_lowercase(self):
        tokens = _tokenize("HELLO World HELLO")
        assert tokens == ["hello", "world", "hello"]

    def test_single_char_removed(self):
        tokens = _tokenize("I went to the park")
        assert "i" not in tokens

    def test_apostrophe_words(self):
        tokens = _tokenize("don't can't won't")
        # These are stop words so they should be removed
        # The apostrophe handling may vary
        for t in tokens:
            assert t not in {"don't", "can't", "won't"} or len(t) > 2

    def test_punctuation_stripped(self):
        tokens = _tokenize("Hello, world! Testing...")
        assert "hello" in tokens
        assert "world" in tokens
        assert "testing" in tokens

    def test_numbers_ignored(self):
        tokens = _tokenize("There are 42 items in the collection")
        # Numbers don't match [a-z']+ pattern
        assert "42" not in tokens


class TestSplitSentences:
    def test_empty(self):
        assert _split_sentences("") == []

    def test_single(self):
        result = _split_sentences("Hello world.")
        assert len(result) == 1

    def test_multiple(self):
        result = _split_sentences("First sentence. Second sentence. Third one!")
        assert len(result) == 3

    def test_question_mark(self):
        result = _split_sentences("What is this? It is a test.")
        assert len(result) == 2

    def test_no_terminator(self):
        result = _split_sentences("no terminator here")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# First occurrence positions
# ---------------------------------------------------------------------------


class TestFirstOccurrencePositions:
    def test_empty(self):
        assert _first_occurrence_positions([]) == {}

    def test_single(self):
        result = _first_occurrence_positions(["hello"])
        assert result == {"hello": 0}

    def test_repeats(self):
        result = _first_occurrence_positions(["a", "b", "a", "c", "b"])
        assert result == {"a": 0, "b": 1, "c": 3}

    def test_all_unique(self):
        result = _first_occurrence_positions(["x", "y", "z"])
        assert result == {"x": 0, "y": 1, "z": 2}


# ---------------------------------------------------------------------------
# Heaps' alpha
# ---------------------------------------------------------------------------


class TestHeapsAlpha:
    def test_zero_total(self):
        assert _heaps_alpha(0, 0) == 0.0

    def test_one_total(self):
        assert _heaps_alpha(1, 1) == 0.0

    def test_all_unique(self):
        # When V == N, α = log(V)/log(N) = 1.0
        assert _heaps_alpha(100, 100) == pytest.approx(1.0)

    def test_half_unique(self):
        # α = log(50)/log(100) ≈ 0.849
        alpha = _heaps_alpha(100, 50)
        assert 0.8 < alpha < 0.9

    def test_few_unique(self):
        alpha = _heaps_alpha(1000, 10)
        assert alpha < 0.4

    def test_zero_unique(self):
        assert _heaps_alpha(100, 0) == 0.0


# ---------------------------------------------------------------------------
# Sentence novelty rates
# ---------------------------------------------------------------------------


class TestSentenceNoveltyRates:
    def test_empty(self):
        assert _sentence_novelty_rates([]) == []

    def test_all_novel(self):
        # First sentence: every word is new
        rates = _sentence_novelty_rates(["alpha beta gamma delta epsilon zeta eta theta."])
        assert len(rates) >= 1
        assert rates[0] == pytest.approx(1.0)

    def test_all_repeated(self):
        # Same words in both sentences
        rates = _sentence_novelty_rates([
            "alpha beta gamma delta. Alpha beta gamma delta."
        ])
        # First sentence: all novel; second: none novel
        assert rates[0] == pytest.approx(1.0)
        assert rates[1] == pytest.approx(0.0)

    def test_mixed(self):
        rates = _sentence_novelty_rates([
            "alpha beta gamma. Alpha delta epsilon."
        ])
        # First: all new; second: alpha is known, delta+epsilon are new → 2/3
        assert rates[0] == pytest.approx(1.0)
        assert rates[1] == pytest.approx(2.0 / 3.0, abs=0.05)


# ---------------------------------------------------------------------------
# Pacing classification
# ---------------------------------------------------------------------------


class TestClassifyPacing:
    def test_very_short_text(self):
        label = _classify_pacing(
            type_token_ratio=0.8,
            front_loading_index=0.5,
            normalised_entropy=0.9,
            heaps_alpha=0.9,
            mean_novelty_rate=0.9,
            total_words=10,
        )
        assert label == "exhausting"

    def test_sparse(self):
        label = _classify_pacing(
            type_token_ratio=0.1,
            front_loading_index=0.5,
            normalised_entropy=0.6,
            heaps_alpha=0.3,
            mean_novelty_rate=0.2,
            total_words=100,
        )
        assert label == "sparse"

    def test_front_loaded(self):
        label = _classify_pacing(
            type_token_ratio=0.5,
            front_loading_index=0.7,
            normalised_entropy=0.6,
            heaps_alpha=0.5,
            mean_novelty_rate=0.3,
            total_words=200,
        )
        assert label == "front_loaded"

    def test_accelerating(self):
        label = _classify_pacing(
            type_token_ratio=0.5,
            front_loading_index=0.3,
            normalised_entropy=0.7,
            heaps_alpha=0.75,
            mean_novelty_rate=0.4,
            total_words=200,
        )
        assert label == "accelerating"

    def test_bursty(self):
        label = _classify_pacing(
            type_token_ratio=0.4,
            front_loading_index=0.5,
            normalised_entropy=0.4,
            heaps_alpha=0.5,
            mean_novelty_rate=0.3,
            total_words=200,
        )
        assert label == "bursty"

    def test_steady(self):
        label = _classify_pacing(
            type_token_ratio=0.4,
            front_loading_index=0.4,
            normalised_entropy=0.7,
            heaps_alpha=0.5,
            mean_novelty_rate=0.35,
            total_words=200,
        )
        assert label == "steady"

    def test_exhausting_high_entropy(self):
        label = _classify_pacing(
            type_token_ratio=0.9,
            front_loading_index=0.5,
            normalised_entropy=0.9,
            heaps_alpha=0.95,
            mean_novelty_rate=0.8,
            total_words=50,
        )
        assert label == "exhausting"


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


class TestComputePacing:
    def test_empty(self):
        result = compute_pacing([])
        assert result["total_words"] == 0
        assert result["pacing_label"] == "sparse"

    def test_all_stopwords(self):
        result = compute_pacing(["the is a and or but not"])
        assert result["total_words"] == 0
        assert result["pacing_label"] == "sparse"

    def test_single_repeated_word(self):
        # "server" is not a stop word
        result = compute_pacing(["server server server server server"])
        assert result["unique_words"] == 1
        assert result["type_token_ratio"] == pytest.approx(0.2)

    def test_all_unique_content_words(self):
        text = "quantum lattice entanglement decoherence superposition wavefunction hamiltonian eigenstate observable fermion boson gluon quark lepton neutrino photon muon tauon meson baryon hadron pion kaon"
        result = compute_pacing([text])
        # 23 unique physics terms, none are stop words
        assert result["unique_words"] == 23
        assert result["type_token_ratio"] == pytest.approx(1.0)

    def test_multi_text(self):
        texts = [
            "The quantum computer processed entangled qubits through a superconducting lattice.",
            "Decoherence limited the computation window before thermal noise overwhelmed the system.",
            "Researchers calibrated the hamiltonian parameters to minimise error rates across all eigenstates.",
        ]
        result = compute_pacing(texts)
        assert result["total_words"] > 0
        assert result["unique_words"] > 0
        assert result["heaps_alpha"] > 0
        assert result["pacing_label"] in {
            "front_loaded", "steady", "bursty", "sparse",
            "accelerating", "exhausting",
        }

    def test_front_loaded_text(self):
        # Short paragraph with all unique words, then long repeat padding.
        # All unique words appear in the first third → front_loading_index = 1.0.
        unique_intro = "Quantum lattice entanglement decoherence superposition wavefunction hamiltonian eigenstate observable fermion boson gluon quark lepton."
        padding = "Quantum lattice entanglement decoherence superposition wavefunction hamiltonian eigenstate observable fermion boson gluon quark lepton. " * 4
        texts = [unique_intro, padding.strip()]
        result = compute_pacing(texts)
        # 15 unique words, total = 15 + 60 = 75, first third = 25 tokens
        # All 15 first-occurrences are at positions 0..14 → all in first third
        assert result["front_loading_index"] == pytest.approx(1.0)
        assert result["pacing_label"] == "front_loaded"

    def test_type_token_ratio_range(self):
        texts = ["Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron."]
        result = compute_pacing(texts)
        assert 0.0 <= result["type_token_ratio"] <= 1.0

    def test_novelty_entropy_range(self):
        texts = [
            "Server crashed because disk filled overnight during backup migration cycle.",
            "Engineer diagnosed memory leak inside container orchestration framework layer.",
            "Debugging revealed race condition within distributed cache invalidation protocol stack.",
        ]
        result = compute_pacing(texts)
        assert 0.0 <= result["novelty_entropy"] <= 1.0


# ---------------------------------------------------------------------------
# On-disk integration
# ---------------------------------------------------------------------------


class TestOnDisk:
    def _make_strokes(self, tmp_path: Path, texts: list) -> Path:
        p = tmp_path / "strokes.jsonl"
        lines = [json.dumps({"text": t, "kind": "test"}) for t in texts]
        p.write_text("\n".join(lines), encoding="utf-8")
        return p

    def test_report_from_file(self, tmp_path):
        path = self._make_strokes(tmp_path, [
            "Distributed systems require consensus protocols for fault tolerance.",
            "Raft achieves consensus through leader election and log replication.",
            "Network partitions create split-brain scenarios that test consistency guarantees.",
        ])
        report = pacing_report(n=10, strokes_path=path)
        assert report["total_words"] > 0
        assert report["pacing_label"] in {
            "front_loaded", "steady", "bursty", "sparse",
            "accelerating", "exhausting",
        }

    def test_empty_file(self, tmp_path):
        path = self._make_strokes(tmp_path, [])
        report = pacing_report(n=10, strokes_path=path)
        assert report["total_words"] == 0

    def test_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.jsonl"
        report = pacing_report(n=10, strokes_path=path)
        assert report["total_words"] == 0

    def test_state(self, tmp_path):
        path = self._make_strokes(tmp_path, [
            "Kubernetes orchestrates container deployments across clustered nodes.",
        ])
        state = pacing_state(strokes_path=path, n=5)
        assert "pacing_label" in state
        assert "total_words" in state

    def test_load_strokes_limit(self, tmp_path):
        texts = [f"Unique text block number {i} with specific content." for i in range(50)]
        path = self._make_strokes(tmp_path, texts)
        strokes = _load_strokes(path, 10)
        assert len(strokes) == 10

    def test_load_strokes_malformed(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text('{"text": "ok"}\nnot json\n{"text": "also ok"}\n', encoding="utf-8")
        strokes = _load_strokes(p, 10)
        assert len(strokes) == 2


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class TestPacingSummary:
    def test_empty(self):
        report = compute_pacing([])
        summary = pacing_summary(report)
        assert "No words" in summary

    def test_normal(self):
        texts = [
            "The quantum computer processed entangled qubits through a superconducting lattice structure.",
            "Decoherence limited the computation window before thermal noise overwhelmed the entire system.",
        ]
        report = compute_pacing(texts)
        summary = pacing_summary(report)
        assert "writer_information_pacing" in summary
        assert "pacing=" in summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCLI:
    def test_cli_default(self, tmp_path):
        strokes_path = tmp_path / "strokes.jsonl"
        strokes_path.write_text(
            json.dumps({"text": "Testing the command line interface for pacing analysis."}),
            encoding="utf-8",
        )
        env_patch = {"DEFAULT_STROKES_PATH": strokes_path}
        # We test by importing and calling _cli directly
        from iamai import writer_information_pacing as mod

        original = mod.DEFAULT_STROKES_PATH
        mod.DEFAULT_STROKES_PATH = strokes_path
        try:
            exit_code = mod._cli(["-n", "5"])
            assert exit_code == 0
        finally:
            mod.DEFAULT_STROKES_PATH = original

    def test_cli_json(self, tmp_path, capsys):
        strokes_path = tmp_path / "strokes.jsonl"
        strokes_path.write_text(
            json.dumps({"text": "Quantum entanglement creates nonlocal correlations between particles."}),
            encoding="utf-8",
        )
        from iamai import writer_information_pacing as mod

        original = mod.DEFAULT_STROKES_PATH
        mod.DEFAULT_STROKES_PATH = strokes_path
        try:
            exit_code = mod._cli(["--json", "-n", "5"])
            assert exit_code == 0
            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert "pacing_label" in data
            assert "total_words" in data
        finally:
            mod.DEFAULT_STROKES_PATH = original

    def test_cli_empty(self, tmp_path, capsys):
        strokes_path = tmp_path / "strokes.jsonl"
        strokes_path.write_text("", encoding="utf-8")
        from iamai import writer_information_pacing as mod

        original = mod.DEFAULT_STROKES_PATH
        mod.DEFAULT_STROKES_PATH = strokes_path
        try:
            exit_code = mod._cli(["-n", "5"])
            assert exit_code == 0
            captured = capsys.readouterr()
            assert "No words" in captured.out
        finally:
            mod.DEFAULT_STROKES_PATH = original
