"""Tests for iamai.stash_accumulation_detector.

stash_accumulation_detector parses ``git stash list`` output, classifies
the health of the stash pile, and recommends cleanup strategies. These
tests cover parsing, health assessment, risk tier classification, and
cleanup recommendations across realistic stash scenarios observed in
this repository.
"""

import pytest
from datetime import datetime, timezone, timedelta

from iamai.stash_accumulation_detector import (
    StashEntry,
    StashHealth,
    parse_stash_list,
    assess_stash_health,
    recommend_cleanup,
    _classify_risk,
    _ORPHAN_THRESHOLD_DAYS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 11, 22, 17, 0, tzinfo=timezone.utc)

EMPTY_STASH = ""

SMALL_CLEAN_STASH = """\
stash@{0}: WIP on main: abc1234 some recent commit
stash@{1}: On main: pre-pull-stash
"""

STASH_WITH_DATES = """\
stash@{0}: WIP on main: abc1234 caretaker visit 793: add module
stash@{1}: WIP on main: def5678 catch-up: commit pending changes before process restart
stash@{2}: On main: pre-pull-stash-2
stash@{3}: WIP on main: 8037f85 caretaker visit 747: add detector — 2026-11-15
stash@{4}: WIP on main: 85163f2 caretaker visit 681: cadence module — 2026-11-05
stash@{5}: WIP on main: 105616a catch-up: commit pending — 2026-10-20
stash@{6}: On main: push_recover auto-stash 2026-10-01T09:02:45+08:00
stash@{7}: WIP on main: 01a0690 catch-up: commit pending — 2026-09-15
"""

LARGE_ORPHAN_STASH = "\n".join(
    f"stash@{{{i}}}: WIP on main: abc{i:04d} catch-up: commit pending — 2026-10-{max(1, 22 - i):02d}"
    for i in range(36)
)


# ---------------------------------------------------------------------------
# StashEntry dataclass
# ---------------------------------------------------------------------------


class TestStashEntry:
    def test_default_fields(self):
        e = StashEntry(index=0, ref="stash@{0}", branch="main", message="test")
        assert e.is_wip is True
        assert e.age_days == 0.0
        assert e.timestamp is None

    def test_is_named_false_for_wip(self):
        e = StashEntry(index=0, ref="stash@{0}", branch="main",
                       message="WIP on main", is_wip=True)
        assert e.is_named is False

    def test_is_named_true_for_labeled(self):
        e = StashEntry(index=0, ref="stash@{0}", branch="main",
                       message="my-label", is_wip=False)
        assert e.is_named is True


# ---------------------------------------------------------------------------
# parse_stash_list
# ---------------------------------------------------------------------------


class TestParseStashList:
    def test_empty_input(self):
        result = parse_stash_list("", now=NOW)
        assert result == []

    def test_whitespace_only(self):
        result = parse_stash_list("   \n  \n  ", now=NOW)
        assert result == []

    def test_parses_wip_entry(self):
        raw = "stash@{0}: WIP on main: abc1234 commit message"
        entries = parse_stash_list(raw, now=NOW)
        assert len(entries) == 1
        assert entries[0].index == 0
        assert entries[0].ref == "stash@{0}"
        assert entries[0].branch == "main"
        assert entries[0].is_wip is True
        assert "commit message" in entries[0].message

    def test_parses_named_entry(self):
        raw = "stash@{1}: On main: pre-pull-stash"
        entries = parse_stash_list(raw, now=NOW)
        assert len(entries) == 1
        assert entries[0].index == 1
        assert entries[0].is_wip is False

    def test_parses_multiple_entries(self):
        entries = parse_stash_list(SMALL_CLEAN_STASH, now=NOW)
        assert len(entries) == 2
        assert entries[0].index == 0
        assert entries[1].index == 1

    def test_extracts_date_from_message(self):
        raw = "stash@{0}: WIP on main: abc1234 visit — 2026-11-10"
        entries = parse_stash_list(raw, now=NOW)
        assert len(entries) == 1
        assert entries[0].timestamp is not None
        assert entries[0].timestamp.year == 2026
        assert entries[0].timestamp.month == 11
        assert entries[0].timestamp.day == 10

    def test_age_calculation_with_date(self):
        raw = "stash@{0}: WIP on main: abc1234 visit — 2026-11-10"
        entries = parse_stash_list(raw, now=NOW)
        # NOW is 17:00 UTC, parsed date is midnight → 12d 17h ≈ 12.7
        assert entries[0].age_days == pytest.approx(12.7, abs=0.5)

    def test_age_zero_without_date(self):
        raw = "stash@{0}: WIP on main: abc1234 no date here"
        entries = parse_stash_list(raw, now=NOW)
        assert entries[0].age_days == 0.0

    def test_large_stash_list(self):
        entries = parse_stash_list(LARGE_ORPHAN_STASH, now=NOW)
        assert len(entries) == 36
        assert entries[0].index == 0
        assert entries[35].index == 35

    def test_malformed_lines_skipped(self):
        raw = "not a stash line\nstash@{0}: WIP on main: abc1234 ok\ngarbage"
        entries = parse_stash_list(raw, now=NOW)
        assert len(entries) == 1

    def test_date_in_iso_format_extracted(self):
        raw = "stash@{6}: On main: push_recover auto-stash 2026-10-01T09:02:45+08:00"
        entries = parse_stash_list(raw, now=NOW)
        assert entries[0].timestamp is not None
        assert entries[0].timestamp.month == 10
        assert entries[0].timestamp.day == 1


# ---------------------------------------------------------------------------
# _classify_risk
# ---------------------------------------------------------------------------


class TestClassifyRisk:
    def test_clean(self):
        assert _classify_risk(0, 0) == "clean"
        assert _classify_risk(2, 2) == "clean"

    def test_nominal(self):
        assert _classify_risk(3, 5) == "nominal"
        assert _classify_risk(5, 6) == "nominal"

    def test_elevated_by_count(self):
        assert _classify_risk(6, 0) == "elevated"
        assert _classify_risk(15, 5) == "elevated"

    def test_elevated_by_age(self):
        assert _classify_risk(2, 8) == "elevated"

    def test_high_by_count(self):
        assert _classify_risk(16, 0) == "high"
        assert _classify_risk(30, 10) == "high"

    def test_high_by_age(self):
        assert _classify_risk(5, 15) == "high"

    def test_critical_by_count(self):
        assert _classify_risk(31, 0) == "critical"
        assert _classify_risk(100, 0) == "critical"

    def test_critical_by_age(self):
        assert _classify_risk(2, 31) == "critical"
        assert _classify_risk(5, 60) == "critical"


# ---------------------------------------------------------------------------
# assess_stash_health
# ---------------------------------------------------------------------------


class TestAssessStashHealth:
    def test_empty_list_is_clean(self):
        health = assess_stash_health([], now=NOW)
        assert health.count == 0
        assert health.risk == "clean"

    def test_small_clean_stash(self):
        entries = parse_stash_list(SMALL_CLEAN_STASH, now=NOW)
        health = assess_stash_health(entries, now=NOW)
        assert health.count == 2
        assert health.wip == 1
        assert health.named == 1
        # Without date hints, age is 0 → clean tier
        assert health.risk == "clean"

    def test_stash_with_dates(self):
        entries = parse_stash_list(STASH_WITH_DATES, now=NOW)
        health = assess_stash_health(entries, now=NOW)
        assert health.count == 8
        # Entries with dates: 2026-11-15 (7d), 2026-11-05 (17d), 2026-10-20 (33d),
        # 2026-10-01 (52d), 2026-09-15 (68d) → max is 68 days
        assert health.aged_days_max > 60
        assert health.risk == "critical"

    def test_orphan_counting(self):
        entries = parse_stash_list(STASH_WITH_DATES, now=NOW)
        health = assess_stash_health(entries, now=NOW)
        # WIP entries with age > 3 days should be counted as orphaned
        assert health.orphaned > 0
        assert health.orphan_ratio > 0

    def test_large_orphan_stash(self):
        entries = parse_stash_list(LARGE_ORPHAN_STASH, now=NOW)
        health = assess_stash_health(entries, now=NOW)
        assert health.count == 36
        assert health.risk == "critical"
        # Most entries are old enough to be orphans
        assert health.orphaned > 20
        assert health.orphan_ratio > 0.5

    def test_median_age(self):
        entries = parse_stash_list(STASH_WITH_DATES, now=NOW)
        health = assess_stash_health(entries, now=NOW)
        # Median should be somewhere in the middle of the ages
        assert health.aged_days_median >= 0

    def test_single_entry(self):
        raw = "stash@{0}: WIP on main: abc1234 test — 2026-11-20"
        entries = parse_stash_list(raw, now=NOW)
        health = assess_stash_health(entries, now=NOW)
        assert health.count == 1
        # NOW is 17:00 UTC, parsed date is midnight → 2d 17h ≈ 2.7
        assert health.aged_days_max == pytest.approx(2.7, abs=0.5)
        assert health.risk == "clean"


# ---------------------------------------------------------------------------
# recommend_cleanup
# ---------------------------------------------------------------------------


class TestRecommendCleanup:
    def test_clean_health_recommends_none(self):
        health = StashHealth(count=2, risk="clean")
        plan = recommend_cleanup(health)
        assert plan["action"] == "none"

    def test_nominal_no_orphans_recommends_none(self):
        health = StashHealth(count=4, orphaned=0, risk="nominal")
        plan = recommend_cleanup(health)
        assert plan["action"] == "none"

    def test_selective_drop_for_mixed_stash(self):
        entries = parse_stash_list(STASH_WITH_DATES, now=NOW)
        health = assess_stash_health(entries, now=NOW)
        plan = recommend_cleanup(health, entries)
        assert plan["action"] in ("selective_drop", "drop_all", "investigate")
        assert "drop_indices" in plan or "reason" in plan

    def test_drop_all_for_mostly_orphaned(self):
        entries = parse_stash_list(LARGE_ORPHAN_STASH, now=NOW)
        health = assess_stash_health(entries, now=NOW)
        plan = recommend_cleanup(health, entries)
        # With >80% orphan ratio and critical risk, should recommend drop_all
        if health.orphan_ratio > 0.8:
            assert plan["action"] == "drop_all"

    def test_investigate_when_no_clear_orphans(self):
        # High count but no orphans — all entries are recent
        health = StashHealth(count=20, orphaned=0, wip=20, risk="high")
        plan = recommend_cleanup(health)
        # Without entries, should suggest investigating or dropping older ones
        assert plan["action"] in ("investigate", "selective_drop")

    def test_cleanup_plan_has_indices(self):
        entries = parse_stash_list(STASH_WITH_DATES, now=NOW)
        health = assess_stash_health(entries, now=NOW)
        plan = recommend_cleanup(health, entries)
        if plan["action"] in ("selective_drop", "drop_all"):
            assert "drop_indices" in plan
            assert isinstance(plan["drop_indices"], list)

    def test_no_action_for_healthy_nominal(self):
        health = StashHealth(count=3, orphaned=0, wip=2, named=1,
                             risk="nominal", orphan_ratio=0.0)
        plan = recommend_cleanup(health)
        assert plan["action"] == "none"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_entry_with_no_date_has_zero_age(self):
        e = StashEntry(index=0, ref="stash@{0}", branch="main",
                       message="no date here", is_wip=True, age_days=0.0)
        health = assess_stash_health([e], now=NOW)
        assert health.aged_days_max == 0.0

    def test_all_named_stashes(self):
        entries = [
            StashEntry(index=i, ref=f"stash@{{{i}}}", branch="main",
                       message=f"label-{i}", is_wip=False, age_days=1.0)
            for i in range(5)
        ]
        health = assess_stash_health(entries, now=NOW)
        assert health.named == 5
        assert health.wip == 0
        assert health.orphaned == 0

    def test_recommend_cleanup_with_none_entries(self):
        health = StashHealth(count=10, orphaned=8, wip=9, risk="high",
                             orphan_ratio=0.8)
        plan = recommend_cleanup(health, entries=None)
        assert "action" in plan

    def test_age_never_negative(self):
        future = "stash@{0}: WIP on main: abc1234 future — 2027-01-01"
        entries = parse_stash_list(future, now=NOW)
        assert entries[0].age_days == 0.0
