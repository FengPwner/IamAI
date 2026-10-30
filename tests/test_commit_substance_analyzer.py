"""Tests for iamai.commit_substance_analyzer — commit substance detection.

22 tests covering:
  - template ratio detection (boilerplate patterns, aphorisms, clean code)
  - lexical novelty computation (Jaccard distance, empty inputs)
  - net info scoring (balance, file diversity, volume)
  - message entropy (identical vs novel messages, normalisation)
  - classification thresholds
  - SubstanceReport aggregate properties
  - CommitEntry dataclass defaults
  - edge cases (empty diffs, zero changes, single commit)
"""

import pytest
from iamai.commit_substance_analyzer import (
    CommitSubstanceAnalyzer,
    CommitEntry,
    SubstanceReport,
    SUBSTANTIAL_THRESHOLD,
    ROUTINE_THRESHOLD,
    _BOILERPLATE_PATTERNS,
    _APHTHORISMS,
)


# ---------------------------------------------------------------------------
# Template ratio
# ---------------------------------------------------------------------------
class TestTemplateRatio:
    def test_pure_boilerplate_detected(self):
        diff = (
            "+## stroke 35320\n"
            "+automation fails quietly, so the log has to say something even when nothing happened.\n"
            "+At this moment: 356200 lines across 1580 tracked files, 95 commits deep.\n"
        )
        ratio = CommitSubstanceAnalyzer.template_ratio(diff)
        assert ratio >= 0.9

    def test_clean_code_low_ratio(self):
        diff = (
            "+def compute_hash(data: bytes) -> str:\n"
            "+    return hashlib.sha256(data).hexdigest()\n"
            "+\n"
            "+class DataValidator:\n"
            "+    def __init__(self, schema: dict):\n"
            "+        self.schema = schema\n"
            "+    def validate(self, record: dict) -> bool:\n"
            "+        return all(k in record for k in self.schema)\n"
        )
        ratio = CommitSubstanceAnalyzer.template_ratio(diff)
        assert ratio == 0.0

    def test_mixed_content_partial_ratio(self):
        diff = (
            "+## stroke 35320\n"
            "+def process_queue(items: list) -> list:\n"
            "+    return [i for i in items if i.is_valid()]\n"
            "+At this moment: 100 files.\n"
        )
        ratio = CommitSubstanceAnalyzer.template_ratio(diff)
        assert 0.3 < ratio < 0.8

    def test_empty_diff_zero_ratio(self):
        assert CommitSubstanceAnalyzer.template_ratio("") == 0.0

    def test_only_deletions_zero_ratio(self):
        diff = (
            "-old line one\n"
            "-old line two\n"
            "--- a/file.py\n"
        )
        assert CommitSubstanceAnalyzer.template_ratio(diff) == 0.0

    def test_aphorism_bank_detected(self):
        diff = (
            "+deleting a file is progress too, eventually.\n"
            "+naming is hard because a bad name is cheap to type and expensive to keep.\n"
        )
        ratio = CommitSubstanceAnalyzer.template_ratio(diff)
        assert ratio >= 0.9


# ---------------------------------------------------------------------------
# Lexical novelty
# ---------------------------------------------------------------------------
class TestLexicalNovelty:
    def test_completely_novel_content(self):
        current = "new function implements binary search with caching"
        previous = ["the quick brown fox jumps over the lazy dog"]
        novelty = CommitSubstanceAnalyzer.lexical_novelty(current, previous)
        assert novelty > 0.8

    def test_identical_content_low_novelty(self):
        text = "automation fails quietly so the log has to say something"
        novelty = CommitSubstanceAnalyzer.lexical_novelty(text, [text, text])
        assert novelty < 0.1

    def test_no_previous_returns_full_novelty(self):
        novelty = CommitSubstanceAnalyzer.lexical_novelty("some content", [])
        assert novelty == 1.0

    def test_empty_current_returns_zero(self):
        novelty = CommitSubstanceAnalyzer.lexical_novelty("", ["some content"])
        assert novelty == 0.0

    def test_partial_overlap_moderate_novelty(self):
        current = "the writer process crashed and was restarted with new PID"
        previous = ["the writer process produces strokes every fifteen seconds"]
        novelty = CommitSubstanceAnalyzer.lexical_novelty(current, previous)
        assert 0.3 < novelty <= 0.8

    def test_multiple_previous_averaged(self):
        current = "unique implementation of binary tree traversal"
        previous = [
            "completely different topic about networking",
            "another unrelated subject regarding databases",
            "yet another thing about file systems",
        ]
        novelty = CommitSubstanceAnalyzer.lexical_novelty(current, previous)
        assert novelty > 0.7


# ---------------------------------------------------------------------------
# Net info score
# ---------------------------------------------------------------------------
class TestNetInfoScore:
    def test_no_changes_zero_score(self):
        score = CommitSubstanceAnalyzer.net_info_score(0, 0, 0)
        assert score == 0.0

    def test_balanced_multi_file_high_score(self):
        score = CommitSubstanceAnalyzer.net_info_score(5, 100, 80)
        assert score > 0.6

    def test_one_sided_single_file_low_score(self):
        # Pure addition, single file → looks like copy-paste
        score = CommitSubstanceAnalyzer.net_info_score(1, 200, 0)
        assert score < 0.5

    def test_refactor_pattern_scores_well(self):
        # Balanced add/delete across multiple files
        score = CommitSubstanceAnalyzer.net_info_score(8, 50, 60)
        assert score > 0.5

    def test_large_diff_diminishing_returns(self):
        small = CommitSubstanceAnalyzer.net_info_score(2, 50, 30)
        huge = CommitSubstanceAnalyzer.net_info_score(2, 5000, 3000)
        # Huge shouldn't be proportionally better
        assert huge < small * 2.0

    def test_zero_files_zero_lines(self):
        score = CommitSubstanceAnalyzer.net_info_score(0, 0, 0)
        assert score == 0.0


# ---------------------------------------------------------------------------
# Message entropy
# ---------------------------------------------------------------------------
class TestMessageEntropy:
    def test_unique_message_full_entropy(self):
        score = CommitSubstanceAnalyzer.message_entropy_score(
            "feat: add commit substance analyzer with Jaccard novelty",
            ["catch-up: commit pending changes before process restart"],
        )
        assert score == 1.0

    def test_identical_messages_low_entropy(self):
        msg = "guoban: note (stroke 195) — 下午差五分两点"
        score = CommitSubstanceAnalyzer.message_entropy_score(msg, [msg, msg, msg])
        assert score == 0.0

    def test_stroke_number_normalised(self):
        current = "guoban: note (stroke 200) — some content"
        previous = [
            "guoban: note (stroke 195) — some content",
            "guoban: note (stroke 190) — some content",
        ]
        score = CommitSubstanceAnalyzer.message_entropy_score(current, previous)
        # After normalising stroke numbers, these become identical
        assert score == 0.0

    def test_no_previous_returns_full(self):
        score = CommitSubstanceAnalyzer.message_entropy_score("any message", [])
        assert score == 1.0

    def test_empty_message_moderate(self):
        score = CommitSubstanceAnalyzer.message_entropy_score("", ["some"])
        assert score == 0.5


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
class TestClassify:
    def test_high_score_substantial(self):
        assert CommitSubstanceAnalyzer.classify(0.8) == "substantial"

    def test_threshold_boundary_substantial(self):
        assert CommitSubstanceAnalyzer.classify(SUBSTANTIAL_THRESHOLD) == "substantial"

    def test_mid_score_routine(self):
        assert CommitSubstanceAnalyzer.classify(0.5) == "routine"

    def test_threshold_boundary_routine(self):
        assert CommitSubstanceAnalyzer.classify(ROUTINE_THRESHOLD) == "routine"

    def test_low_score_filler(self):
        assert CommitSubstanceAnalyzer.classify(0.2) == "filler"

    def test_zero_is_filler(self):
        assert CommitSubstanceAnalyzer.classify(0.0) == "filler"


# ---------------------------------------------------------------------------
# SubstanceReport
# ---------------------------------------------------------------------------
class TestSubstanceReport:
    def test_empty_report(self):
        r = SubstanceReport()
        assert r.substance_ratio == 0.0
        assert r.filler_count == 0
        assert r.avg_score == 0.0

    def test_all_substantial(self):
        entries = [CommitEntry(label="substantial", score=0.8) for _ in range(5)]
        r = SubstanceReport(entries=entries)
        assert r.substance_ratio == 1.0
        assert r.substantial_count == 5
        assert r.filler_count == 0

    def test_mixed_labels(self):
        entries = [
            CommitEntry(label="substantial", score=0.8),
            CommitEntry(label="routine", score=0.5),
            CommitEntry(label="filler", score=0.2),
            CommitEntry(label="filler", score=0.1),
        ]
        r = SubstanceReport(entries=entries)
        assert r.substance_ratio == 0.5  # 2 non-filler out of 4
        assert r.filler_count == 2
        assert r.substantial_count == 1
        assert r.routine_count == 1
        assert abs(r.avg_score - 0.4) < 0.01

    def test_summary_format(self):
        entries = [
            CommitEntry(label="substantial", score=0.9),
            CommitEntry(label="routine", score=0.5),
        ]
        r = SubstanceReport(entries=entries)
        s = r.summary
        assert "50%" in s or "100%" in s  # substance_ratio
        assert "2 commits" in s


# ---------------------------------------------------------------------------
# CommitEntry defaults
# ---------------------------------------------------------------------------
class TestCommitEntry:
    def test_defaults(self):
        e = CommitEntry()
        assert e.sha == ""
        assert e.label == "routine"
        assert e.score == 0.5
        assert e.files_changed == 0

    def test_custom_values(self):
        e = CommitEntry(sha="abc1234", label="filler", score=0.2,
                        files_changed=3, lines_added=100, lines_deleted=5)
        assert e.sha == "abc1234"
        assert e.label == "filler"
        assert e.lines_added == 100


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------
class TestConstants:
    def test_thresholds_ordered(self):
        assert SUBSTANTIAL_THRESHOLD > ROUTINE_THRESHOLD > 0

    def test_weights_sum_to_one(self):
        from iamai.commit_substance_analyzer import (
            TEMPLATE_RATIO_WEIGHT, NOVELTY_WEIGHT,
            NET_INFO_WEIGHT, MESSAGE_ENTROPY_WEIGHT,
        )
        total = (TEMPLATE_RATIO_WEIGHT + NOVELTY_WEIGHT
                 + NET_INFO_WEIGHT + MESSAGE_ENTROPY_WEIGHT)
        assert abs(total - 1.0) < 1e-9

    def test_boilerplate_patterns_nonempty(self):
        assert len(_BOILERPLATE_PATTERNS) > 0

    def test_aphorisms_nonempty(self):
        assert len(_APHTHORISMS) > 0
