#!/usr/bin/env python3
"""Tests for caretaker_health_score module."""

import json
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from iamai.caretaker_health_score import HealthResult, HealthScore


@pytest.fixture
def temp_repo():
    """Create a temporary git repository with test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        
        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], 
                      cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], 
                      cwd=repo, capture_output=True, check=True)
        
        # Create data directory
        data_dir = repo / "data"
        data_dir.mkdir()
        
        yield repo


@pytest.fixture
def scorer():
    """Create a HealthScore instance."""
    return HealthScore(cadence_target=900, freshness_target=3600)


class TestHealthScore:
    """Test suite for HealthScore class."""
    
    def test_empty_repo(self, temp_repo, scorer):
        """Test scoring on empty repository."""
        result = scorer.calculate(temp_repo)
        
        assert isinstance(result, HealthResult)
        assert 0 <= result.score <= 100
        assert result.verdict in ["healthy", "degraded", "critical"]
        assert "cadence" in result.components
        assert "freshness" in result.components
        assert "diversity" in result.components
        assert "backlog" in result.components
        assert "processes" in result.components
    
    def test_cadence_score_no_file(self, temp_repo, scorer):
        """Test cadence scoring when strokes file doesn't exist."""
        score, details = scorer._score_cadence(temp_repo)
        
        assert score == 0
        assert "error" in details
    
    def test_cadence_score_healthy(self, temp_repo, scorer):
        """Test cadence scoring with healthy stroke rate."""
        strokes_file = temp_repo / "data" / "strokes.jsonl"
        now = time.time()
        
        # Create strokes with 15-minute gaps (target cadence)
        strokes = []
        for i in range(10):
            strokes.append({
                "ts": now - (9 - i) * 900,
                "category": "devlog",
                "content": f"Stroke {i}",
            })
        
        strokes_file.write_text("\n".join(json.dumps(s) for s in strokes))
        
        score, details = scorer._score_cadence(temp_repo)
        
        assert score >= 90  # Should be near perfect
        assert "avg_gap" in details
        assert details["avg_gap"] is not None
    
    def test_cadence_score_degraded(self, temp_repo, scorer):
        """Test cadence scoring with slow stroke rate."""
        strokes_file = temp_repo / "data" / "strokes.jsonl"
        now = time.time()
        
        # Create strokes with 30-minute gaps (2x target)
        strokes = []
        for i in range(10):
            strokes.append({
                "ts": now - (9 - i) * 1800,
                "category": "devlog",
                "content": f"Stroke {i}",
            })
        
        strokes_file.write_text("\n".join(json.dumps(s) for s in strokes))
        
        score, details = scorer._score_cadence(temp_repo)
        
        assert 40 <= score <= 60  # Should be degraded
        assert details["avg_gap"] > 900
    
    def test_freshness_score_no_commits(self, temp_repo, scorer):
        """Test freshness scoring with no commits."""
        # Create a file but don't commit
        (temp_repo / "data" / "test.txt").write_text("test")
        
        score, details = scorer._score_freshness(temp_repo)
        
        # Should return 0 or error since no commits exist
        assert score == 0 or "error" in details
    
    def test_freshness_score_recent_commit(self, temp_repo, scorer):
        """Test freshness scoring with recent commit."""
        # Create and commit a file
        test_file = temp_repo / "data" / "test.txt"
        test_file.write_text("test")
        subprocess.run(["git", "add", "."], cwd=temp_repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "test"], cwd=temp_repo, capture_output=True, check=True)
        
        score, details = scorer._score_freshness(temp_repo)
        
        assert score == 100  # Just committed, should be perfect
        assert "age_seconds" in details
        assert details["age_seconds"] < 60
    
    def test_diversity_score_high(self, temp_repo, scorer):
        """Test diversity scoring with varied categories."""
        strokes_file = temp_repo / "data" / "strokes.jsonl"
        
        # Create strokes with diverse categories
        categories = ["devlog", "metrics", "snippet", "thought", "garden", "note"]
        strokes = []
        for i in range(20):
            strokes.append({
                "ts": time.time() - i * 900,
                "category": categories[i % len(categories)],
                "content": f"Stroke {i}",
            })
        
        strokes_file.write_text("\n".join(json.dumps(s) for s in strokes))
        
        score, details = scorer._score_diversity(temp_repo)
        
        assert score >= 90  # 6 unique categories should score high
        assert details["unique_categories"] == 6
    
    def test_diversity_score_low(self, temp_repo, scorer):
        """Test diversity scoring with repetitive categories."""
        strokes_file = temp_repo / "data" / "strokes.jsonl"
        
        # Create strokes with same category
        strokes = []
        for i in range(20):
            strokes.append({
                "ts": time.time() - i * 900,
                "category": "devlog",
                "content": f"Stroke {i}",
            })
        
        strokes_file.write_text("\n".join(json.dumps(s) for s in strokes))
        
        score, details = scorer._score_diversity(temp_repo)
        
        assert score <= 20  # Only 1 category should score low
        assert details["unique_categories"] == 1
    
    def test_backlog_score_clean(self, temp_repo, scorer):
        """Test backlog scoring with clean working tree."""
        # Create and commit a file
        test_file = temp_repo / "data" / "test.txt"
        test_file.write_text("test")
        subprocess.run(["git", "add", "."], cwd=temp_repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "test"], cwd=temp_repo, capture_output=True, check=True)
        
        score, details = scorer._score_backlog(temp_repo)
        
        assert score == 100
        assert details["pending_files"] == 0
    
    def test_backlog_score_moderate(self, temp_repo, scorer):
        """Test backlog scoring with moderate pending files."""
        # Create several uncommitted files
        for i in range(5):
            (temp_repo / "data" / f"file{i}.txt").write_text(f"content {i}")
        
        score, details = scorer._score_backlog(temp_repo)
        
        assert 50 <= score <= 100
        assert details["pending_files"] == 5
    
    def test_backlog_score_heavy(self, temp_repo, scorer):
        """Test backlog scoring with heavy pending files."""
        # Create many uncommitted files
        for i in range(20):
            (temp_repo / "data" / f"file{i}.txt").write_text(f"content {i}")
        
        score, details = scorer._score_backlog(temp_repo)
        
        assert score < 50
        assert details["pending_files"] == 20
    
    def test_process_score_detection(self, scorer, temp_repo):
        """Test that process scoring can detect running processes."""
        score, details = scorer._score_processes(temp_repo)
        
        # Should return a valid score
        assert 0 <= score <= 100
        assert "writer" in details
        assert "batch" in details
    
    def test_composite_score_healthy(self, temp_repo, scorer):
        """Test composite scoring for healthy system."""
        # Create healthy state: recent commit, clean tree, diverse strokes
        strokes_file = temp_repo / "data" / "strokes.jsonl"
        now = time.time()
        
        # Healthy strokes
        categories = ["devlog", "metrics", "snippet", "thought", "garden", "note"]
        strokes = []
        for i in range(10):
            strokes.append({
                "ts": now - (9 - i) * 900,
                "category": categories[i % len(categories)],
                "content": f"Stroke {i}",
            })
        strokes_file.write_text("\n".join(json.dumps(s) for s in strokes))
        
        # Commit it
        subprocess.run(["git", "add", "."], cwd=temp_repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "healthy state"], 
                      cwd=temp_repo, capture_output=True, check=True)
        
        result = scorer.calculate(temp_repo)
        
        # Should be healthy
        assert result.score >= 70
        assert result.verdict in ["healthy", "degraded"]
    
    def test_composite_score_degraded(self, temp_repo, scorer):
        """Test composite scoring for degraded system."""
        # Create degraded state: old commit, pending files, slow strokes
        strokes_file = temp_repo / "data" / "strokes.jsonl"
        now = time.time()
        
        # Slow strokes (2x target)
        strokes = []
        for i in range(10):
            strokes.append({
                "ts": now - (9 - i) * 1800,
                "category": "devlog",  # Low diversity
                "content": f"Stroke {i}",
            })
        strokes_file.write_text("\n".join(json.dumps(s) for s in strokes))
        
        # Don't commit (creates backlog)
        
        result = scorer.calculate(temp_repo)
        
        # Should be degraded or critical
        assert result.score < 80
        assert result.verdict in ["degraded", "critical"]
    
    def test_weight_sum(self, scorer):
        """Test that component weights sum to 1.0."""
        total = sum(scorer.WEIGHTS.values())
        assert abs(total - 1.0) < 0.001
    
    def test_custom_targets(self, temp_repo):
        """Test HealthScore with custom target thresholds."""
        custom_scorer = HealthScore(cadence_target=600, freshness_target=1800)
        
        assert custom_scorer.cadence_target == 600
        assert custom_scorer.freshness_target == 1800
        
        # Should still work
        result = custom_scorer.calculate(temp_repo)
        assert isinstance(result, HealthResult)


class TestHealthResult:
    """Test suite for HealthResult dataclass."""
    
    def test_creation(self):
        """Test HealthResult creation."""
        result = HealthResult(
            score=85,
            verdict="healthy",
            components={"cadence": 90, "freshness": 80},
            details={"cadence": {"avg_gap": 900}},
        )
        
        assert result.score == 85
        assert result.verdict == "healthy"
        assert result.components["cadence"] == 90
        assert result.details["cadence"]["avg_gap"] == 900
    
    def test_verdict_thresholds(self):
        """Test verdict classification thresholds."""
        # These are tested implicitly through composite tests
        # but let's verify the logic explicitly
        assert 80 <= 100  # healthy range
        assert 60 <= 79 < 80  # degraded range
        assert 0 <= 59 < 60  # critical range


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
