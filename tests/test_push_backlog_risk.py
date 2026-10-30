"""Tests for iamai.push_backlog_risk — push backlog risk assessment."""

import pytest
from iamai.push_backlog_risk import (
    BacklogRisk,
    RiskTier,
    assess,
)


# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------

class TestTierClassification:
    """Verify that risk tiers are assigned correctly based on inputs."""

    def test_low_risk_fresh_small_backlog(self):
        r = assess(
            unpushed_count=3,
            oldest_age_s=600,
            ssh_present=True,
            ssh_registered=True,
        )
        assert r.tier == RiskTier.LOW

    def test_low_risk_zero_commits(self):
        r = assess(
            unpushed_count=0,
            oldest_age_s=0,
            ssh_present=True,
            ssh_registered=True,
        )
        assert r.tier == RiskTier.LOW

    def test_medium_risk_moderate_backlog(self):
        r = assess(
            unpushed_count=10,
            oldest_age_s=1800,
            ssh_present=True,
            ssh_registered=True,
        )
        assert r.tier == RiskTier.MEDIUM

    def test_medium_risk_old_commit_overrides_count(self):
        """Even with few commits, an old commit pushes tier to MEDIUM."""
        r = assess(
            unpushed_count=2,
            oldest_age_s=7200,  # 2 hours
            ssh_present=True,
            ssh_registered=True,
        )
        assert r.tier == RiskTier.MEDIUM

    def test_high_risk_large_backlog(self):
        r = assess(
            unpushed_count=30,
            oldest_age_s=3600,
            ssh_present=True,
            ssh_registered=False,
        )
        assert r.tier == RiskTier.HIGH

    def test_high_risk_very_old_commit(self):
        r = assess(
            unpushed_count=5,
            oldest_age_s=43200,  # 12 hours
            ssh_present=True,
            ssh_registered=True,
        )
        assert r.tier == RiskTier.HIGH

    def test_critical_risk_massive_backlog(self):
        r = assess(
            unpushed_count=75,
            oldest_age_s=7200,
            ssh_present=True,
            ssh_registered=False,
        )
        assert r.tier == RiskTier.CRITICAL

    def test_critical_risk_day_old_commits(self):
        r = assess(
            unpushed_count=10,
            oldest_age_s=100000,  # > 24 hours
            ssh_present=True,
            ssh_registered=True,
        )
        assert r.tier == RiskTier.CRITICAL

    def test_critical_risk_missing_ssh_key(self):
        r = assess(
            unpushed_count=1,
            oldest_age_s=60,
            ssh_present=False,
            ssh_registered=False,
        )
        assert r.tier == RiskTier.CRITICAL


# ---------------------------------------------------------------------------
# Summary construction
# ---------------------------------------------------------------------------

class TestSummary:
    """Verify that the summary string contains relevant information."""

    def test_summary_includes_count(self):
        r = assess(
            unpushed_count=42,
            oldest_age_s=3600,
            ssh_present=True,
            ssh_registered=True,
        )
        assert "42 unpushed commits" in r.summary

    def test_summary_mentions_missing_key(self):
        r = assess(
            unpushed_count=5,
            oldest_age_s=300,
            ssh_present=False,
            ssh_registered=False,
        )
        assert "SSH key MISSING" in r.summary

    def test_summary_mentions_unregistered_key(self):
        r = assess(
            unpushed_count=5,
            oldest_age_s=300,
            ssh_present=True,
            ssh_registered=False,
        )
        assert "not registered" in r.summary

    def test_summary_omits_age_when_fresh(self):
        r = assess(
            unpushed_count=3,
            oldest_age_s=120,
            ssh_present=True,
            ssh_registered=True,
        )
        assert "old" not in r.summary.lower() or "oldest" not in r.summary.lower()


# ---------------------------------------------------------------------------
# Data class behavior
# ---------------------------------------------------------------------------

class TestDataClass:
    """Verify BacklogRisk dataclass works as expected."""

    def test_as_dict_keys(self):
        r = assess(
            unpushed_count=10,
            oldest_age_s=3600,
            ssh_present=True,
            ssh_registered=False,
        )
        d = r.as_dict()
        expected_keys = {
            "tier", "unpushed_count", "oldest_commit_age_s",
            "ssh_key_present", "ssh_key_registered", "summary",
        }
        assert set(d.keys()) == expected_keys

    def test_as_dict_tier_is_string(self):
        r = assess(
            unpushed_count=0,
            oldest_age_s=0,
            ssh_present=True,
            ssh_registered=True,
        )
        assert isinstance(r.as_dict()["tier"], str)
        assert r.as_dict()["tier"] == "LOW"

    def test_frozen_dataclass(self):
        r = assess(
            unpushed_count=5,
            oldest_age_s=100,
            ssh_present=True,
            ssh_registered=True,
        )
        with pytest.raises(AttributeError):
            r.tier = RiskTier.CRITICAL  # type: ignore[misc]

    def test_oldest_age_rounded_in_dict(self):
        r = assess(
            unpushed_count=1,
            oldest_age_s=123.456789,
            ssh_present=True,
            ssh_registered=True,
        )
        assert r.as_dict()["oldest_commit_age_s"] == 123.5


# ---------------------------------------------------------------------------
# Boundary conditions
# ---------------------------------------------------------------------------

class TestBoundaries:
    """Edge cases at tier boundaries."""

    def test_exactly_5_commits_is_low(self):
        r = assess(
            unpushed_count=5,
            oldest_age_s=300,
            ssh_present=True,
            ssh_registered=True,
        )
        assert r.tier == RiskTier.LOW

    def test_exactly_6_commits_is_medium(self):
        r = assess(
            unpushed_count=6,
            oldest_age_s=300,
            ssh_present=True,
            ssh_registered=True,
        )
        assert r.tier == RiskTier.MEDIUM

    def test_exactly_20_commits_is_medium(self):
        r = assess(
            unpushed_count=20,
            oldest_age_s=300,
            ssh_present=True,
            ssh_registered=True,
        )
        assert r.tier == RiskTier.MEDIUM

    def test_exactly_21_commits_is_high(self):
        r = assess(
            unpushed_count=21,
            oldest_age_s=300,
            ssh_present=True,
            ssh_registered=True,
        )
        assert r.tier == RiskTier.HIGH

    def test_exactly_50_commits_is_high(self):
        r = assess(
            unpushed_count=50,
            oldest_age_s=300,
            ssh_present=True,
            ssh_registered=True,
        )
        assert r.tier == RiskTier.HIGH

    def test_exactly_51_commits_is_critical(self):
        r = assess(
            unpushed_count=51,
            oldest_age_s=300,
            ssh_present=True,
            ssh_registered=True,
        )
        assert r.tier == RiskTier.CRITICAL

    def test_exactly_one_hour_is_medium(self):
        r = assess(
            unpushed_count=3,
            oldest_age_s=3601,
            ssh_present=True,
            ssh_registered=True,
        )
        assert r.tier == RiskTier.MEDIUM

    def test_exactly_six_hours_is_high(self):
        r = assess(
            unpushed_count=3,
            oldest_age_s=21601,
            ssh_present=True,
            ssh_registered=True,
        )
        assert r.tier == RiskTier.HIGH

    def test_exactly_24_hours_is_critical(self):
        r = assess(
            unpushed_count=3,
            oldest_age_s=86401,
            ssh_present=True,
            ssh_registered=True,
        )
        assert r.tier == RiskTier.CRITICAL


# ---------------------------------------------------------------------------
# RiskTier enum
# ---------------------------------------------------------------------------

class TestRiskTier:
    """Enum value correctness."""

    def test_enum_values(self):
        assert RiskTier.LOW.value == "LOW"
        assert RiskTier.MEDIUM.value == "MEDIUM"
        assert RiskTier.HIGH.value == "HIGH"
        assert RiskTier.CRITICAL.value == "CRITICAL"

    def test_all_tiers_are_strings(self):
        for tier in RiskTier:
            assert isinstance(tier.value, str)
