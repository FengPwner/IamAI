#!/usr/bin/env python3
"""Tests for writer_hedging_language module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_hedging_language import (
    HedgingResult,
    measure_hedging,
    _find_hedge_words,
    _find_booster_words,
    _find_phrases,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_hedging("")
        assert r.hedge_count == 0
        assert r.booster_count == 0
        assert r.classification == "unknown"

    def test_whitespace_only(self):
        r = measure_hedging("   \n\n   ")
        assert r.classification == "unknown"

    def test_no_markers(self):
        r = measure_hedging("The server crashed at midnight. The backup restored data by dawn.")
        assert r.hedge_count == 0
        assert r.booster_count == 0
        assert r.classification == "direct"

    def test_single_word_no_markers(self):
        r = measure_hedging("Hello.")
        assert r.total_words == 1
        assert r.classification == "direct"

    def test_punctuation_only_words(self):
        r = measure_hedging("! @ # $ %")
        assert r.total_words == 0
        assert r.classification == "unknown"


# ── hedge word detection ────────────────────────────────────────


class TestHedgeWordDetection:
    def test_might(self):
        r = measure_hedging("The server might be overloaded.")
        assert r.hedge_count >= 1
        assert "might" in r.hedge_word_counts

    def test_maybe(self):
        r = measure_hedging("Maybe the cache is stale.")
        assert r.hedge_count >= 1
        assert "maybe" in r.hedge_word_counts

    def test_perhaps(self):
        r = measure_hedging("Perhaps the timeout is too low.")
        assert r.hedge_count >= 1
        assert "perhaps" in r.hedge_word_counts

    def test_possibly(self):
        r = measure_hedging("This could possibly fix the issue.")
        assert r.hedge_count >= 2  # could + possibly
        assert "possibly" in r.hedge_word_counts
        assert "could" in r.hedge_word_counts

    def test_somewhat(self):
        r = measure_hedging("The performance is somewhat degraded.")
        assert r.hedge_count >= 1
        assert "somewhat" in r.hedge_word_counts

    def test_slightly(self):
        r = measure_hedging("Latency is slightly elevated today.")
        assert r.hedge_count >= 1
        assert "slightly" in r.hedge_word_counts

    def test_arguably(self):
        r = measure_hedging("This is arguably the best approach.")
        assert r.hedge_count >= 1
        assert "arguably" in r.hedge_word_counts

    def test_seemingly(self):
        r = measure_hedging("The fix seemingly resolved the crash.")
        assert r.hedge_count >= 1
        assert "seemingly" in r.hedge_word_counts

    def test_multiple_hedges_in_one_sentence(self):
        r = measure_hedging("It might perhaps somewhat tend to suggest a minor issue.")
        assert r.hedge_count >= 3

    def test_case_insensitive(self):
        r = measure_hedging("MAYBE the server crashed. Perhaps the backup failed.")
        assert r.hedge_count >= 2


# ── hedge phrase detection ──────────────────────────────────────


class TestHedgePhraseDetection:
    def test_sort_of(self):
        r = measure_hedging("The fix sort of works for now.")
        assert r.hedge_phrase_counts
        assert any("sort" in k for k in r.hedge_phrase_counts)

    def test_kind_of(self):
        r = measure_hedging("It kind of depends on the load.")
        assert r.hedge_phrase_counts
        assert any("kind" in k for k in r.hedge_phrase_counts)

    def test_to_some_extent(self):
        r = measure_hedging("This is true to some extent.")
        assert r.hedge_phrase_counts

    def test_in_a_way(self):
        r = measure_hedging("It works in a way that avoids the bug.")
        assert r.hedge_phrase_counts

    def test_it_seems(self):
        r = measure_hedging("It seems the server is down again.")
        assert r.hedge_phrase_counts
        assert any("seems" in k or "seem" in k for k in r.hedge_phrase_counts)

    def test_it_appears(self):
        r = measure_hedging("It appears the logs were rotated.")
        assert r.hedge_phrase_counts

    def test_tends_to(self):
        r = measure_hedging("The system tends to slow down under load.")
        assert r.hedge_phrase_counts

    def test_seems_to(self):
        r = measure_hedging("The cache seems to expire too quickly.")
        assert r.hedge_phrase_counts

    def test_more_or_less(self):
        r = measure_hedging("The deployment is more or less complete.")
        assert r.hedge_phrase_counts

    def test_not_entirely(self):
        r = measure_hedging("The fix is not entirely satisfactory.")
        assert r.hedge_phrase_counts

    def test_multiple_phrases(self):
        text = "It seems the server sort of tends to crash when it kind of gets overloaded."
        r = measure_hedging(text)
        assert r.hedge_count >= 3


# ── booster word detection ──────────────────────────────────────


class TestBoosterWordDetection:
    def test_clearly(self):
        r = measure_hedging("The bug is clearly in the parser.")
        assert r.booster_count >= 1
        assert "clearly" in r.booster_word_counts

    def test_obviously(self):
        r = measure_hedging("Obviously, the server needs more memory.")
        assert r.booster_count >= 1
        assert "obviously" in r.booster_word_counts

    def test_definitely(self):
        r = measure_hedging("This definitely fixes the race condition.")
        assert r.booster_count >= 1
        assert "definitely" in r.booster_word_counts

    def test_certainly(self):
        r = measure_hedging("The fix will certainly improve throughput.")
        assert r.booster_count >= 1
        assert "certainly" in r.booster_word_counts

    def test_undoubtedly(self):
        r = measure_hedging("This is undoubtedly the root cause.")
        assert r.booster_count >= 1

    def test_evidently(self):
        r = measure_hedging("Evidently the config was wrong.")
        assert r.booster_count >= 1

    def test_absolutely(self):
        r = measure_hedging("The patch absolutely resolved the issue.")
        assert r.booster_count >= 1

    def test_precisely(self):
        r = measure_hedging("This is precisely where the bug lives.")
        assert r.booster_count >= 1

    def test_case_insensitive(self):
        r = measure_hedging("CLEARLY the fix works. OBVIOUSLY the tests pass.")
        assert r.booster_count >= 2


# ── booster phrase detection ────────────────────────────────────


class TestBoosterPhraseDetection:
    def test_without_doubt(self):
        r = measure_hedging("This is without doubt the best solution.")
        assert r.booster_phrase_counts

    def test_no_doubt(self):
        r = measure_hedging("No doubt the server will recover.")
        assert r.booster_phrase_counts

    def test_of_course(self):
        r = measure_hedging("Of course the backup was tested.")
        assert r.booster_phrase_counts

    def test_it_is_clear(self):
        r = measure_hedging("It is clear that the patch works.")
        assert r.booster_phrase_counts

    def test_beyond_question(self):
        r = measure_hedging("The fix is beyond question effective.")
        assert r.booster_phrase_counts

    def test_beyond_reasonable_doubt(self):
        r = measure_hedging("This proves beyond reasonable doubt that the bug is fixed.")
        assert r.booster_phrase_counts


# ── hedge ratio ─────────────────────────────────────────────────


class TestHedgeRatio:
    def test_all_hedges(self):
        text = "Perhaps maybe possibly the server might crash."
        r = measure_hedging(text)
        assert r.hedge_ratio == 1.0

    def test_all_boosters(self):
        text = "Clearly obviously definitely certainly the fix works."
        r = measure_hedging(text)
        assert r.hedge_ratio == 0.0

    def test_balanced(self):
        text = (
            "Perhaps the server crashed. "
            "Clearly the backup worked. "
            "Maybe the config was wrong. "
            "Obviously the fix helped."
        )
        r = measure_hedging(text)
        assert 0.4 <= r.hedge_ratio <= 0.6

    def test_no_markers_neutral_ratio(self):
        text = "The server processed 42 requests per second."
        r = measure_hedging(text)
        assert r.hedge_ratio == 0.5  # neutral when no markers


# ── rate computation ─────────────────────────────────────────────


class TestRateComputation:
    def test_hedge_rate_per_100_words(self):
        # 10 words with 1 hedge = rate of 10 per 100 words
        text = "Perhaps the server crashed at midnight last night in production."
        r = measure_hedging(text)
        # 1 hedge, ~10 words → rate ≈ 10.0
        assert r.hedge_rate > 5.0

    def test_booster_rate_per_100_words(self):
        text = "Clearly the fix definitely works in every single case we tested."
        r = measure_hedging(text)
        assert r.booster_rate > 10.0

    def test_zero_rate_when_no_markers(self):
        text = "The server processed requests efficiently all day long without errors."
        r = measure_hedging(text)
        assert r.hedge_rate == 0.0
        assert r.booster_rate == 0.0


# ── classification ──────────────────────────────────────────────


class TestClassification:
    def test_direct_no_markers(self):
        text = (
            "The server processed 42 requests per second. "
            "Latency averaged 12 milliseconds. "
            "The cache hit rate reached 94 percent. "
            "Uptime held at 99.9 percent throughout the quarter."
        )
        r = measure_hedging(text)
        assert r.classification == "direct"

    def test_measured_moderate_hedging(self):
        text = (
            "The server might be under-provisioned for peak traffic. "
            "The cache probably expires too quickly under load. "
            "We could increase the TTL to reduce stale reads. "
            "The logs suggest the bottleneck is in the query planner. "
            "Performance improved after the index rebuild last week. "
            "Users reported faster response times after the change. "
            "The database replication lag stayed under two milliseconds. "
            "Queue depth never exceeded the configured threshold. "
            "The monitoring dashboard showed green across all services. "
            "Incident count dropped to zero for the entire month. "
            "The load balancer distributed traffic evenly across nodes. "
            "CPU utilization averaged forty percent throughout the period. "
            "Memory usage remained stable at three gigabytes per instance. "
            "Disk IO stayed well within the provisioned IOPS limits. "
            "Network throughput peaked at eight hundred megabits per second."
        )
        r = measure_hedging(text)
        assert r.classification in ("measured", "tentative")

    def test_tentative_heavy_hedging(self):
        text = (
            "The server might perhaps be somewhat overloaded. "
            "It seems the cache kind of tends to expire too fast. "
            "Maybe the configuration could possibly be slightly wrong. "
            "Perhaps the timeout might sort of need adjustment."
        )
        r = measure_hedging(text)
        assert r.classification in ("tentative", "evasive")

    def test_evasive_excessive_hedging(self):
        # Many hedges packed into a short text
        hedges = [
            "perhaps", "maybe", "possibly", "might", "could",
            "somewhat", "slightly", "seemingly", "arguably",
            "sort of", "kind of", "tends to", "seems to",
            "more or less", "to some extent",
        ]
        text = "The system " + " ".join(hedges) + " functions adequately."
        r = measure_hedging(text)
        assert r.classification in ("evasive", "mixed_signals")

    def test_booster_heavy(self):
        text = (
            "Clearly the fix obviously works. "
            "Definitely the best approach without doubt. "
            "Certainly the tests prove the solution. "
            "Absolutely no question about it."
        )
        r = measure_hedging(text)
        assert r.classification in ("booster_heavy", "mixed_signals")

    def test_mixed_signals(self):
        text = (
            "Perhaps maybe possibly the server might crash. "
            "Clearly obviously definitely the fix works. "
            "It seems the cache sort of tends to fail. "
            "Certainly undoubtedly the backup is fine."
        )
        r = measure_hedging(text)
        # Both hedges and boosters present at high rates
        assert r.hedge_count >= 5
        assert r.booster_count >= 3


# ── top markers ─────────────────────────────────────────────────


class TestTopMarkers:
    def test_top_hedges_limited_to_five(self):
        text = (
            "Perhaps the server crashed. Maybe the cache failed. "
            "Possibly the disk was full. Might be the network. "
            "Could be the config. Somewhat degraded performance. "
            "Slightly elevated latency. Rather slow responses."
        )
        r = measure_hedging(text)
        assert len(r.top_hedges) <= 5
        assert len(r.top_hedges) > 0

    def test_top_boosters_limited_to_five(self):
        text = (
            "Clearly the fix works. Obviously the tests pass. "
            "Definitely the best approach. Certainly effective. "
            "Undoubtedly the right solution. Evidently successful. "
            "Plainly the correct answer."
        )
        r = measure_hedging(text)
        assert len(r.top_boosters) <= 5
        assert len(r.top_boosters) > 0

    def test_top_hedges_ordered_by_frequency(self):
        text = "Perhaps perhaps perhaps maybe maybe possibly."
        r = measure_hedging(text)
        assert r.top_hedges[0][0] == "perhaps"
        assert r.top_hedges[0][1] == 3

    def test_top_boosters_ordered_by_frequency(self):
        text = "Clearly clearly clearly obviously obviously."
        r = measure_hedging(text)
        assert r.top_boosters[0][0] == "clearly"
        assert r.top_boosters[0][1] == 3


# ── edge cases ───────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_word_text(self):
        r = measure_hedging("Hello.")
        assert r.total_words == 1
        assert r.classification == "direct"

    def test_single_hedge_word(self):
        r = measure_hedging("Perhaps.")
        assert r.hedge_count == 1
        assert r.hedge_rate == 100.0

    def test_repeated_same_hedge(self):
        r = measure_hedging("Maybe maybe maybe maybe maybe.")
        assert r.hedge_count == 5
        assert r.hedge_word_counts["maybe"] == 5

    def test_long_text_no_markers(self):
        words = ["The", "server", "processed", "request", "number"] * 50
        text = " ".join(words) + "."
        r = measure_hedging(text)
        assert r.total_words == 250
        assert r.hedge_count == 0
        assert r.booster_count == 0

    def test_mixed_punctuation(self):
        r = measure_hedging("Perhaps? Maybe! Clearly. Obviously...")
        assert r.hedge_count >= 2
        assert r.booster_count >= 2

    def test_apostrophes_in_words(self):
        r = measure_hedging("It's clearly the server's fault.")
        assert r.booster_count >= 1

    def test_hedge_in_question(self):
        r = measure_hedging("Could this perhaps be the issue?")
        assert r.hedge_count >= 2

    def test_booster_in_exclamation(self):
        r = measure_hedging("Obviously! The fix clearly works!")
        assert r.booster_count >= 2


# ── orthogonality ────────────────────────────────────────────────


class TestOrthogonality:
    def test_short_can_be_hedged(self):
        r = measure_hedging("It might perhaps sort of work.")
        assert r.classification in ("tentative", "evasive")

    def test_long_can_be_direct(self):
        sentences = [
            "The server processed %d requests." % i for i in range(20)
        ]
        text = " ".join(sentences)
        r = measure_hedging(text)
        assert r.classification == "direct"

    def test_formal_can_be_direct(self):
        text = (
            "The experiment yielded significant results. "
            "The control group showed no change. "
            "The hypothesis was confirmed by the data."
        )
        r = measure_hedging(text)
        assert r.classification == "direct"

    def test_formal_can_be_hedged(self):
        text = (
            "The experiment might perhaps suggest a possible correlation. "
            "It seems the results could somewhat indicate a trend. "
            "One might arguably say the data tends to support the hypothesis."
        )
        r = measure_hedging(text)
        assert r.classification in ("tentative", "evasive")

    def test_informal_can_be_direct(self):
        text = "The server crashed. I fixed it. Deployed the patch. Done."
        r = measure_hedging(text)
        assert r.classification == "direct"

    def test_informal_can_be_hedged(self):
        text = "So like the server kind of crashed maybe and it sort of seems broken."
        r = measure_hedging(text)
        assert r.classification in ("tentative", "evasive")


# ── real-world scenarios ────────────────────────────────────────


class TestRealWorldScenarios:
    def test_academic_hedging(self):
        text = (
            "These results suggest that the intervention may have a modest "
            "effect on outcomes. The data appears to indicate a possible "
            "correlation between dosage and response rate, though the "
            "sample size somewhat limits the generalizability of these "
            "findings. Further research would likely be needed to confirm "
            "these preliminary observations."
        )
        r = measure_hedging(text)
        assert r.hedge_count >= 5
        # Dense hedging in short text → evasive is correct
        assert r.classification in ("tentative", "evasive")

    def test_overconfident_pitch_deck(self):
        text = (
            "Our solution clearly addresses the market need. "
            "Obviously our technology is superior to competitors. "
            "Definitely the best investment opportunity this quarter. "
            "Without doubt this will generate exceptional returns. "
            "The market is absolutely ready for disruption."
        )
        r = measure_hedging(text)
        assert r.booster_count >= 4
        assert r.classification in ("booster_heavy", "mixed_signals")

    def test_engineering_postmortem(self):
        text = (
            "The server crashed at 14:32 UTC due to an OOM condition. "
            "The heap grew to 8GB over 45 minutes. The memory leak "
            "originated in the connection pool handler. We patched "
            "the leak and deployed the fix at 15:10 UTC. Service "
            "restored to full capacity by 15:15 UTC."
        )
        r = measure_hedging(text)
        assert r.hedge_count == 0
        assert r.booster_count == 0
        assert r.classification == "direct"

    def test_cautious_code_review(self):
        text = (
            "This approach might work for small datasets but could "
            "possibly struggle with larger inputs. The error handling "
            "seems somewhat incomplete. Perhaps consider adding retry "
            "logic. The naming is arguably unclear — it might help "
            "to rename the variable for readability."
        )
        r = measure_hedging(text)
        assert r.hedge_count >= 4
        # Heavy hedging in short text → evasive is correct
        assert r.classification in ("tentative", "evasive")


# ── dataclass defaults ──────────────────────────────────────────


class TestDataclassDefaults:
    def test_result_defaults(self):
        r = HedgingResult()
        assert r.hedge_count == 0
        assert r.booster_count == 0
        assert r.total_words == 0
        assert r.hedge_rate == 0.0
        assert r.booster_rate == 0.0
        assert r.hedge_ratio == 0.0
        assert r.hedge_word_counts == {}
        assert r.hedge_phrase_counts == {}
        assert r.booster_word_counts == {}
        assert r.booster_phrase_counts == {}
        assert r.top_hedges == []
        assert r.top_boosters == []
        assert r.classification == "unknown"


# ── helper function tests ───────────────────────────────────────


class TestHelperFunctions:
    def test_find_hedge_words_basic(self):
        words = ["Perhaps", "the", "server", "might", "crash"]
        counts = _find_hedge_words(words)
        assert counts["perhaps"] == 1
        assert counts["might"] == 1
        assert "server" not in counts

    def test_find_hedge_words_empty(self):
        counts = _find_hedge_words(["the", "server", "crashed"])
        assert counts == {}

    def test_find_booster_words_basic(self):
        words = ["Clearly", "the", "fix", "obviously", "works"]
        counts = _find_booster_words(words)
        assert counts["clearly"] == 1
        assert counts["obviously"] == 1

    def test_find_booster_words_empty(self):
        counts = _find_booster_words(["the", "server", "crashed"])
        assert counts == {}

    def test_find_phrases_basic(self):
        text = "It seems the server sort of tends to crash."
        counts = _find_phrases(text, [r"\bsort\s+of\b", r"\bit\s+seems?\b", r"\btends?\s+to\b"])
        assert len(counts) == 3

    def test_find_phrases_no_match(self):
        text = "The server crashed at midnight."
        counts = _find_phrases(text, [r"\bsort\s+of\b", r"\bkind\s+of\b"])
        assert counts == {}


# ── word count accuracy ─────────────────────────────────────────


class TestWordCountAccuracy:
    def test_word_count_simple(self):
        r = measure_hedging("The quick brown fox jumps.")
        assert r.total_words == 5

    def test_word_count_with_hyphens(self):
        r = measure_hedging("The well-known server crashed.")
        # "well" and "known" counted separately (split on non-alpha)
        assert r.total_words >= 3

    def test_word_count_with_numbers(self):
        r = measure_hedging("Server 42 processed 1000 requests.")
        # Only alpha words counted: Server, processed, requests
        assert r.total_words == 3

    def test_word_count_with_contractions(self):
        r = measure_hedging("It's clearly the server's fault.")
        # "It's" → "It" and "s"; "server's" → "server" and "s"
        assert r.total_words >= 4


# ── classification boundary tests ───────────────────────────────


class TestClassificationBoundaries:
    def test_just_below_tentative_threshold(self):
        # Need hedge_rate < 1.5 for "measured"
        # 1 hedge in 100 words = rate of 1.0
        words = ["maybe"] + ["the"] * 99
        text = " ".join(words) + "."
        r = measure_hedging(text)
        assert r.classification == "direct" or r.classification == "measured"

    def test_direct_classification_threshold(self):
        # hedge_rate < 0.5 and booster_rate < 0.3
        words = ["The", "server", "processed", "requests", "all", "day",
                 "without", "any", "errors", "whatsoever"]
        text = " ".join(words) + "."
        r = measure_hedging(text)
        assert r.classification == "direct"
