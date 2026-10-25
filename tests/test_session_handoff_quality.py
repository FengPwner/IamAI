#!/usr/bin/env python3
"""tests for scripts/session_handoff_quality.py — caretaker handoff analyzer."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from session_handoff_quality import (
    tokenize,
    extract_sections,
    score_handoff_presence,
    score_followthrough,
    score_context_continuity,
    score_pending_tracking,
    compute_handoff_quality,
    format_bar,
)


# ── tokenizer ────────────────────────────────────────────────────────


class TestTokenize:
    def test_basic_extraction(self):
        tokens = tokenize("add handoff quality module")
        assert "handoff" in tokens
        assert "quality" in tokens
        assert "module" in tokens

    def test_drops_short_words(self):
        tokens = tokenize("fix a bug in the code")
        assert "bug" in tokens
        assert "code" in tokens
        assert "fix" not in tokens  # stop word
        assert "the" not in tokens

    def test_drops_stop_words(self):
        tokens = tokenize("update the documentation for the new feature")
        assert "documentation" in tokens
        assert "feature" in tokens
        assert "update" not in tokens  # stop word
        assert "the" not in tokens

    def test_empty_input(self):
        tokens = tokenize("")
        assert tokens == set()

    def test_only_stop_words(self):
        tokens = tokenize("the and for with")
        assert tokens == set()


# ── section extraction ───────────────────────────────────────────────


class TestExtractSections:
    def test_basic_sections(self):
        content = """# Summary
this is the summary

## Next Steps
- do this
- do that

## Open Items
- item one
"""
        sections = extract_sections(content)
        assert "summary" in sections
        assert "next steps" in sections
        assert "open items" in sections

    def test_no_headings(self):
        content = "just some plain text\nwithout headings"
        sections = extract_sections(content)
        assert "intro" in sections
        assert "just some plain text" in sections["intro"]

    def test_nested_headings(self):
        content = """# Main
intro

## Sub1
content

### Sub2
more content
"""
        sections = extract_sections(content)
        assert "main" in sections
        assert "sub1" in sections
        assert "sub2" in sections


# ── metric 1: handoff presence ──────────────────────────────────────


class TestHandoffPresence:
    def test_clear_handoff_section(self):
        content = """# Visit 338

## Summary
completed work on coherence analyzer

## Next Steps
- need to add tests for edge cases
- should update documentation
- fix performance issue in tokenizer
"""
        score, detail = score_handoff_presence(content)
        assert score <= 5, f"expected low score for good handoff, got {score}"
        assert "actionable" in detail.lower()

    def test_summary_section_only(self):
        content = """# Visit 338

## Summary
this visit focused on adding the handoff quality tool
"""
        score, detail = score_handoff_presence(content)
        assert 5 <= score <= 15, f"expected moderate score, got {score}"

    def test_no_handoff_section(self):
        content = """# Visit 338

just some notes about what was done
no clear structure
"""
        score, detail = score_handoff_presence(content)
        assert score >= 15, f"expected high score for missing handoff, got {score}"

    def test_bullet_list_fallback(self):
        content = """# Visit 338

- did this thing
- also that thing
- and another thing
"""
        score, detail = score_handoff_presence(content)
        assert 10 <= score <= 20, f"expected moderate score for bullets, got {score}"
        assert "bullet" in detail.lower()

    def test_empty_content(self):
        score, detail = score_handoff_presence("")
        assert score == 25


# ── metric 2: followthrough ──────────────────────────────────────────


class TestFollowthrough:
    def test_good_followthrough(self):
        previous = """# Visit 337

## Recommendations
- add coherence analyzer
- update documentation
- fix tokenizer performance
"""
        current = """# Visit 338

added the coherence analyzer module
updated documentation for all metrics
improved tokenizer performance with caching
"""
        score, detail = score_followthrough(current, previous)
        assert score <= 10, f"expected low score for good followthrough, got {score}"

    def test_partial_followthrough(self):
        previous = """# Visit 337

## Next Steps
- add coherence analyzer
- update documentation
- fix tokenizer
- add more tests
"""
        current = """# Visit 338

worked on the coherence analyzer
some other unrelated work
"""
        score, detail = score_followthrough(current, previous)
        assert 10 <= score <= 20, f"expected moderate score, got {score}"

    def test_no_followthrough(self):
        previous = """# Visit 337

## Recommendations
- add coherence analyzer
- update documentation
"""
        current = """# Visit 338

completely different topic
nothing related to previous recommendations
"""
        score, detail = score_followthrough(current, previous)
        assert score >= 20, f"expected high score for no followthrough, got {score}"

    def test_no_previous(self):
        score, detail = score_followthrough("current content", "")
        assert score == 0
        assert "no previous" in detail.lower()


# ── metric 3: context continuity ─────────────────────────────────────


class TestContextContinuity:
    def test_strong_continuity(self):
        previous = """
caretaker visit focused on repository health metrics
added coherence analyzer with topic continuity scoring
implemented tokenizer for commit message analysis
"""
        current = """
continued work on repository health metrics
extended coherence analyzer with narrative thread metric
improved tokenizer stop word filtering
"""
        score, detail = score_context_continuity(current, previous)
        assert score <= 10, f"expected low score for strong continuity, got {score}"

    def test_moderate_continuity(self):
        previous = "worked on repository monitoring tools and caretaker visit tracking"
        current = "added handoff quality measurement for caretaker visits and tracking continuity"
        score, detail = score_context_continuity(current, previous)
        assert 5 <= score <= 20, f"expected moderate score, got {score}"

    def test_weak_continuity(self):
        previous = """
focused on commit batching and push gate logic
"""
        current = """
completely different work on documentation formatting
"""
        score, detail = score_context_continuity(current, previous)
        assert score >= 20, f"expected high score for weak continuity, got {score}"

    def test_no_previous(self):
        score, detail = score_context_continuity("content", "")
        assert score == 0


# ── metric 4: pending items tracking ─────────────────────────────────


class TestPendingTracking:
    def test_good_pending_section(self):
        content = """# Visit 338

## Pending Items
- need to add edge case tests
- should improve performance
- investigate memory usage
- update configuration docs
"""
        score, detail = score_pending_tracking(content)
        assert score <= 5, f"expected low score for good pending section, got {score}"
        assert "4" in detail or "item" in detail.lower()

    def test_minimal_pending_section(self):
        content = """# Visit 338

## Open Items
- one thing to do
"""
        score, detail = score_pending_tracking(content)
        assert 5 <= score <= 15, f"expected moderate score, got {score}"

    def test_no_pending_section(self):
        content = """# Visit 338

just completed some work
no documentation of open items
"""
        score, detail = score_pending_tracking(content)
        assert score >= 20, f"expected high score for missing pending, got {score}"

    def test_inline_todo_markers(self):
        content = """# Visit 338

completed the main feature
TODO: add tests later
FIXME: performance issue
"""
        score, detail = score_pending_tracking(content)
        assert 5 <= score <= 15, f"expected moderate score for inline TODOs, got {score}"
        assert "todo" in detail.lower()


# ── aggregation ──────────────────────────────────────────────────────


class TestComputeHandoffQuality:
    def test_seamless_handoff(self):
        current = """# Visit 338

## Summary
completed coherence analyzer with four metrics and comprehensive tests

## Next Steps
- need to add more metrics for session quality
- should update documentation with examples
- consider adding dashboard integration

## Pending Items
- edge case tests
- performance review
- documentation update
"""
        previous = """# Visit 337

## Recommendations
- add coherence analyzer module
- improve metrics coverage across visits
- update documentation with examples
"""
        result = compute_handoff_quality(current, previous)
        assert result["total_score"] <= 40, f"expected low total, got {result['total_score']}"
        assert result["grade"] in ("SEAMLESS", "SMOOTH")

    def test_broken_handoff(self):
        current = """# Visit 338

random work with no structure
"""
        previous = """# Visit 337

completely different topic
"""
        result = compute_handoff_quality(current, previous)
        assert result["total_score"] >= 60, f"expected high total, got {result['total_score']}"
        assert result["grade"] in ("ROUGH", "BROKEN")

    def test_all_metrics_present(self):
        result = compute_handoff_quality("content", "previous")
        assert "handoff_note_presence" in result["metrics"]
        assert "recommendation_followthrough" in result["metrics"]
        assert "context_continuity" in result["metrics"]
        assert "pending_items_tracking" in result["metrics"]

    def test_score_ranges(self):
        result = compute_handoff_quality("content", "previous")
        assert 0 <= result["total_score"] <= 100
        for metric in result["metrics"].values():
            assert 0 <= metric["score"] <= 25
            assert metric["max"] == 25


# ── formatting ───────────────────────────────────────────────────────


class TestFormatBar:
    def test_zero_score(self):
        bar = format_bar(0, 25, 20)
        assert bar == "[" + "-" * 20 + "]"

    def test_full_score(self):
        bar = format_bar(25, 25, 20)
        assert bar == "[" + "#" * 20 + "]"

    def test_half_score(self):
        bar = format_bar(12, 25, 20)
        assert bar.startswith("[")
        assert bar.endswith("]")
        assert "#" in bar
        assert "-" in bar

    def test_custom_width(self):
        bar = format_bar(10, 25, 10)
        assert len(bar) == 12  # 10 + 2 brackets
