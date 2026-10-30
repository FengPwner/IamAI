"""
test_handoff_manager.py — Tests for handoff_manager module.

Ensures the handoff artifact system works correctly for maintaining
continuity between caretaker visits.
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

# Add tools directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from handoff_manager import (
    HANDOFF_FILE,
    create_handoff,
    is_stale,
    load_handoff,
    read_handoff,
    STALE_THRESHOLD_HOURS,
)


@pytest.fixture
def temp_handoff_dir(tmp_path):
    """Create a temporary directory for handoff file."""
    temp_file = tmp_path / "HANDOFF.md"
    with patch("handoff_manager.HANDOFF_FILE", temp_file):
        yield temp_file


class TestHandoffCreation:
    """Tests for creating handoff documents."""
    
    def test_create_empty_handoff(self, temp_handoff_dir):
        """Create handoff with no sections."""
        result = create_handoff()
        assert result["status"] == "created"
        assert result["sections"] == 0
        assert temp_handoff_dir.exists()
    
    def test_create_handoff_with_active_threads(self, temp_handoff_dir):
        """Create handoff with active investigations."""
        result = create_handoff(
            active_threads=["Investigating stall patterns", "Testing commit timing"]
        )
        assert result["status"] == "created"
        assert result["sections"] == 1
        
        content = temp_handoff_dir.read_text()
        assert "## Active threads" in content
        assert "Investigating stall patterns" in content
        assert "Testing commit timing" in content
    
    def test_create_handoff_with_observations(self, temp_handoff_dir):
        """Create handoff with observations."""
        result = create_handoff(
            observations=["Writer more stable after restart", "Batch intervals consistent"]
        )
        assert result["sections"] == 1
        
        content = temp_handoff_dir.read_text()
        assert "## Observations" in content
        assert "Writer more stable" in content
    
    def test_create_handoff_with_all_sections(self, temp_handoff_dir):
        """Create handoff with all section types."""
        result = create_handoff(
            active_threads=["Thread 1"],
            observations=["Obs 1"],
            deprioritized=["Depri 1"],
            anomalies=["Anomaly 1"]
        )
        assert result["sections"] == 4
        
        content = temp_handoff_dir.read_text()
        assert "## Active threads" in content
        assert "## Observations" in content
        assert "## Deprioritized" in content
        assert "## Anomalies explained" in content
    
    def test_create_handoff_includes_timestamp(self, temp_handoff_dir):
        """Verify timestamp is included in handoff."""
        result = create_handoff(active_threads=["Test"])
        
        content = temp_handoff_dir.read_text()
        assert "# Handoff —" in content
        assert result["timestamp"] in content
    
    def test_create_handoff_overwrites_existing(self, temp_handoff_dir):
        """Creating new handoff overwrites previous one."""
        create_handoff(active_threads=["Old thread"])
        create_handoff(active_threads=["New thread"])
        
        content = temp_handoff_dir.read_text()
        assert "New thread" in content
        assert "Old thread" not in content


class TestHandoffReading:
    """Tests for reading handoff documents."""
    
    def test_read_missing_handoff(self, temp_handoff_dir):
        """Reading when no handoff exists."""
        result = read_handoff()
        assert result["status"] == "missing"
        assert "No handoff document exists" in result["message"]
    
    def test_read_fresh_handoff(self, temp_handoff_dir):
        """Reading a recently created handoff."""
        create_handoff(active_threads=["Test thread"])
        result = read_handoff()
        
        assert result["status"] == "fresh"
        assert result["timestamp"] is not None
        assert result["age_hours"] is not None
        assert result["age_hours"] < 1  # Just created
    
    def test_read_stale_handoff(self, temp_handoff_dir):
        """Reading an old handoff."""
        create_handoff(active_threads=["Old thread"])
        
        # Manually modify timestamp to be old
        old_time = (datetime.now() - timedelta(hours=30)).isoformat(timespec="seconds")
        content = temp_handoff_dir.read_text()
        content = content.replace(
            content.split("—")[1].strip().split("\n")[0],
            old_time
        )
        temp_handoff_dir.write_text(content)
        
        result = read_handoff()
        assert result["status"] == "stale"
        assert result["age_hours"] > STALE_THRESHOLD_HOURS
    
    def test_read_handoff_content_preview(self, temp_handoff_dir):
        """Verify content preview is included."""
        create_handoff(
            active_threads=["Test"],
            observations=["Observation 1", "Observation 2"]
        )
        result = read_handoff()
        
        assert "content_preview" in result
        assert "## Active threads" in result["content_preview"]


class TestStalenessCheck:
    """Tests for staleness detection."""
    
    def test_none_timestamp_is_stale(self):
        """No timestamp means stale."""
        assert is_stale(None) is True
    
    def test_recent_timestamp_is_fresh(self):
        """Recent timestamp is not stale."""
        recent = datetime.now() - timedelta(hours=1)
        assert is_stale(recent) is False
    
    def test_old_timestamp_is_stale(self):
        """Old timestamp is stale."""
        old = datetime.now() - timedelta(hours=30)
        assert is_stale(old) is True
    
    def test_threshold_boundary(self):
        """Test exact threshold boundary."""
        just_under = datetime.now() - timedelta(hours=STALE_THRESHOLD_HOURS - 1)
        just_over = datetime.now() - timedelta(hours=STALE_THRESHOLD_HOURS + 1)
        
        assert is_stale(just_under) is False
        assert is_stale(just_over) is True


class TestHandoffLoading:
    """Tests for loading handoff documents."""
    
    def test_load_nonexistent(self, temp_handoff_dir):
        """Loading when file doesn't exist."""
        result = load_handoff()
        assert result is None
    
    def test_load_existing(self, temp_handoff_dir):
        """Loading an existing handoff."""
        create_handoff(active_threads=["Test"])
        result = load_handoff()
        
        assert result is not None
        assert "content" in result
        assert "timestamp" in result
        assert "stale" in result
    
    def test_load_parses_timestamp(self, temp_handoff_dir):
        """Verify timestamp is correctly parsed."""
        create_handoff(active_threads=["Test"])
        result = load_handoff()
        
        assert result["timestamp"] is not None
        assert isinstance(result["timestamp"], datetime)
    
    def test_load_handles_malformed_timestamp(self, temp_handoff_dir):
        """Loading handoff with malformed timestamp."""
        temp_handoff_dir.write_text("# Handoff — invalid-timestamp\n\n## Test\n")
        result = load_handoff()
        
        assert result is not None
        assert result["timestamp"] is None
        assert result["stale"] is True  # No timestamp = stale


class TestHandoffFormat:
    """Tests for handoff document format."""
    
    def test_checkbox_format_for_threads(self, temp_handoff_dir):
        """Active threads use checkbox format."""
        create_handoff(active_threads=["Task 1", "Task 2"])
        content = temp_handoff_dir.read_text()
        
        assert "- [ ] Task 1" in content
        assert "- [ ] Task 2" in content
    
    def test_bullet_format_for_observations(self, temp_handoff_dir):
        """Observations use bullet format."""
        create_handoff(observations=["Obs 1", "Obs 2"])
        content = temp_handoff_dir.read_text()
        
        assert "- Obs 1" in content
        assert "- Obs 2" in content
    
    def test_sections_separated_by_blank_lines(self, temp_handoff_dir):
        """Sections are properly separated."""
        create_handoff(
            active_threads=["Thread"],
            observations=["Obs"]
        )
        content = temp_handoff_dir.read_text()
        
        # Should have blank line between sections
        assert "\n\n## Observations" in content


class TestIntegration:
    """Integration tests for handoff workflow."""
    
    def test_full_workflow(self, temp_handoff_dir):
        """Test complete create-read-check workflow."""
        # Create
        create_result = create_handoff(
            active_threads=["Investigating X"],
            observations=["Y is stable"],
            deprioritized=["Z not urgent"],
            anomalies=["W was maintenance"]
        )
        assert create_result["status"] == "created"
        
        # Read
        read_result = read_handoff()
        assert read_result["status"] == "fresh"
        assert "Investigating X" in read_result["content_preview"]
        
        # Check staleness
        handoff = load_handoff()
        assert handoff["stale"] is False
    
    def test_update_workflow(self, temp_handoff_dir):
        """Test updating handoff over time."""
        # Initial handoff
        create_handoff(active_threads=["Initial task"])
        
        # Update with new information
        create_handoff(
            active_threads=["Initial task", "New task"],
            observations=["New observation"]
        )
        
        result = read_handoff()
        assert "New task" in result["content_preview"]
        assert "New observation" in result["content_preview"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
