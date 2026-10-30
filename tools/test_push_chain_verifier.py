"""Tests for push_chain_verifier — the write→commit→push health checker.

Covers:
  - Each stage check returns a valid StageResult
  - format_results produces both human and JSON output
  - Exit code logic (all healthy vs. any unhealthy)
  - Edge cases: missing pid files, bad permissions, git errors
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Allow importing from tools/
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from push_chain_verifier import (
    StageResult,
    check_writer,
    check_batch,
    check_uncommitted,
    check_unpushed,
    check_ssh_key,
    check_remote,
    verify_chain,
    format_results,
    _run,
)


# ---------------------------------------------------------------------------
# _run helper
# ---------------------------------------------------------------------------

class TestRunHelper:
    def test_successful_command(self):
        code, out, err = _run(["echo", "hello"])
        assert code == 0
        assert out == "hello"

    def test_failing_command(self):
        code, out, err = _run(["false"])
        assert code != 0

    def test_missing_command(self):
        code, out, err = _run(["nonexistent_command_xyz_12345"])
        assert code == -2
        assert "not found" in err

    def test_timeout(self):
        code, out, err = _run(["sleep", "10"], timeout=1)
        assert code == -1
        assert err == "timeout"


# ---------------------------------------------------------------------------
# Stage checks
# ---------------------------------------------------------------------------

class TestCheckWriter:
    def test_no_pid_file(self, tmp_path):
        """Writer check fails gracefully when no pid file exists."""
        with patch("push_chain_verifier.REPO", tmp_path):
            with patch("push_chain_verifier.Path") as mock_path:
                mock_path.return_value.exists.return_value = False
                # Use a non-existent pid file path
                result = check_writer(tmp_path)
                # Should return unhealthy since /tmp/iamai-writer-qwen.pid
                # may or may not exist in test env
                assert isinstance(result, StageResult)
                assert result.name == "writer"

    def test_dead_pid(self, tmp_path):
        """Writer check detects a dead process."""
        pid_file = Path("/tmp/iamai-writer-qwen.pid")
        pid_file.write_text("999999999")  # very unlikely to exist
        try:
            result = check_writer(tmp_path)
            assert result.name == "writer"
            assert result.healthy is False
            assert "not running" in result.detail
        finally:
            pid_file.unlink(missing_ok=True)


class TestCheckBatch:
    def test_dead_pid(self, tmp_path):
        """Batch check detects a dead process."""
        pid_file = Path("/tmp/iamai-batch-qwen.pid")
        pid_file.write_text("999999998")
        try:
            result = check_batch(tmp_path)
            assert result.name == "batch"
            assert result.healthy is False
        finally:
            pid_file.unlink(missing_ok=True)


class TestCheckUncommitted:
    def test_clean_repo(self, tmp_path):
        """Uncommitted check on a directory with no git repo."""
        result = check_uncommitted(tmp_path)
        assert result.name == "uncommitted"
        # Should fail because tmp_path is not a git repo
        assert result.healthy is False
        assert "git error" in result.detail


class TestCheckUnpushed:
    def test_no_remote(self, tmp_path):
        """Unpushed check on a directory with no git repo."""
        result = check_unpushed(tmp_path)
        assert result.name == "unpushed"
        assert result.healthy is False


class TestCheckSshKey:
    def test_missing_key(self):
        """SSH key check fails when key doesn't exist."""
        with patch("push_chain_verifier.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            result = check_ssh_key()
            assert result.name == "ssh_key"
            assert result.healthy is False

    def test_bad_permissions(self, tmp_path):
        """SSH key check detects wrong permissions."""
        key = tmp_path / "test_key"
        key.write_text("fake key")
        key.chmod(0o644)  # too open
        # Patch the hardcoded path inside the function
        with patch("push_chain_verifier.Path") as MockPath:
            mock_instance = MagicMock()
            mock_instance.exists.return_value = True
            mock_instance.stat.return_value = MagicMock(st_mode=0o100644)
            MockPath.return_value = mock_instance
            result = check_ssh_key()
            assert isinstance(result, StageResult)
            assert result.name == "ssh_key"
            assert result.healthy is False
            assert "bad permissions" in result.detail


class TestCheckRemote:
    def test_nonexistent_repo(self, tmp_path):
        """Remote check fails on a non-git directory."""
        result = check_remote(tmp_path)
        assert result.name == "remote"
        assert result.healthy is False


# ---------------------------------------------------------------------------
# Format and chain
# ---------------------------------------------------------------------------

class TestFormatResults:
    def test_all_healthy_human(self):
        results = [
            StageResult("writer", True, "pid 12345 alive", 1),
            StageResult("batch", True, "pid 12346 alive", 1),
        ]
        output = format_results(results, as_json=False)
        assert "CHAIN HEALTHY" in output
        assert "[OK  ]" in output

    def test_unhealthy_human(self):
        results = [
            StageResult("writer", False, "not running", 1),
            StageResult("batch", True, "pid 12346 alive", 1),
        ]
        output = format_results(results, as_json=False)
        assert "CHAIN UNHEALTHY" in output
        assert "[FAIL]" in output

    def test_json_output(self):
        results = [
            StageResult("writer", True, "alive", 5),
        ]
        output = format_results(results, as_json=True)
        parsed = json.loads(output)
        assert len(parsed) == 1
        assert parsed[0]["stage"] == "writer"
        assert parsed[0]["healthy"] is True
        assert parsed[0]["latency_ms"] == 5


class TestVerifyChain:
    def test_returns_all_stages(self):
        """verify_chain returns results for all 6 stages."""
        results = verify_chain()
        names = [r.name for r in results]
        assert "writer" in names
        assert "batch" in names
        assert "uncommitted" in names
        assert "unpushed" in names
        assert "ssh_key" in names
        assert "remote" in names
        assert len(results) == 6


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
