"""Tests for stall_classifier module."""

import pytest

from iamai.stall_classifier import classify_stall, stall_advice


class TestClassifyStall:
    def test_healthy_writer(self):
        """Gap less than cadence is ok."""
        assert classify_stall(10, 15) == "ok"
        assert classify_stall(14, 15) == "ok"
        assert classify_stall(0, 15) == "ok"

    def test_recoverable_stall(self):
        """Gap between 1x and 2x cadence is recoverable."""
        assert classify_stall(15, 15) == "recoverable"
        assert classify_stall(20, 15) == "recoverable"
        assert classify_stall(29, 15) == "recoverable"

    def test_concerning_stall(self):
        """Gap between 2x and 4x cadence is concerning."""
        assert classify_stall(30, 15) == "concerning"
        assert classify_stall(45, 15) == "concerning"
        assert classify_stall(59, 15) == "concerning"

    def test_critical_stall(self):
        """Gap >= 4x cadence is critical."""
        assert classify_stall(60, 15) == "critical"
        assert classify_stall(120, 15) == "critical"
        assert classify_stall(1000, 15) == "critical"

    def test_custom_cadence(self):
        """Works with non-default cadence values."""
        assert classify_stall(30, 30) == "recoverable"
        assert classify_stall(90, 30) == "concerning"
        assert classify_stall(150, 30) == "critical"

    def test_boundary_values(self):
        """Boundary conditions are handled correctly."""
        # Exactly at cadence
        assert classify_stall(15, 15) == "recoverable"
        # Exactly at 2x
        assert classify_stall(30, 15) == "concerning"
        # Exactly at 4x
        assert classify_stall(60, 15) == "critical"


class TestStallAdvice:
    def test_known_severities(self):
        """All known severities return advice."""
        assert "healthy" in stall_advice("ok").lower()
        assert "monitor" in stall_advice("recoverable").lower()
        assert "restart" in stall_advice("concerning").lower()
        assert "immediately" in stall_advice("critical").lower()

    def test_unknown_severity(self):
        """Unknown severity returns a fallback message."""
        result = stall_advice("unknown_level")
        assert "unknown" in result.lower()
        assert "unknown_level" in result
