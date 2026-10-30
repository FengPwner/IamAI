"""Tests for iamai.ssh_key_rescue — SSH key permission rescue on FUSE mounts.

The rescue module solves a specific but recurring problem: SSH keys on
FUSE-mounted workspaces get 0777 permissions that chmod cannot fix,
causing silent push failures. These tests verify detection, rescue,
and idempotency.
"""

import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.ssh_key_rescue import (
    DEFAULT_KEY_PATH,
    RESCUE_DIR,
    RESCUE_KEY,
    _is_too_open,
    _chmod_works,
    needs_rescue,
    rescue_key,
    rescue_env,
)


# ---------------------------------------------------------------------------
# _is_too_open
# ---------------------------------------------------------------------------

class TestIsTooOpen:
    """Verify permission threshold detection."""

    def test_missing_file_returns_false(self, tmp_path):
        missing = tmp_path / "nonexistent"
        assert _is_too_open(missing) is False

    def test_600_is_not_too_open(self, tmp_path):
        key = tmp_path / "id_test"
        key.write_text("fake-key-content")
        os.chmod(str(key), 0o600)
        assert _is_too_open(key) is False

    def test_777_is_too_open(self, tmp_path):
        key = tmp_path / "id_test"
        key.write_text("fake-key-content")
        os.chmod(str(key), 0o777)
        assert _is_too_open(key) is True

    def test_644_is_too_open(self, tmp_path):
        key = tmp_path / "id_test"
        key.write_text("fake-key-content")
        os.chmod(str(key), 0o644)
        assert _is_too_open(key) is True

    def test_400_is_not_too_open(self, tmp_path):
        key = tmp_path / "id_test"
        key.write_text("fake-key-content")
        os.chmod(str(key), 0o400)
        assert _is_too_open(key) is False


# ---------------------------------------------------------------------------
# _chmod_works
# ---------------------------------------------------------------------------

class TestChmodWorks:
    """Verify filesystem chmod capability detection."""

    def test_chmod_works_on_tmpfs(self, tmp_path):
        key = tmp_path / "id_test"
        key.write_text("fake-key-content")
        os.chmod(str(key), 0o777)
        # On tmpfs, chmod works: _chmod_works returns True
        assert _chmod_works(key) is True
        # Note: _chmod_works restores original permissions in finally block,
        # so the file remains 0o777 after the call — this is by design.
        assert key.stat().st_mode & 0o777 == 0o777

    def test_missing_file_returns_false(self, tmp_path):
        missing = tmp_path / "nonexistent"
        assert _chmod_works(missing) is False


# ---------------------------------------------------------------------------
# needs_rescue
# ---------------------------------------------------------------------------

class TestNeedsRescue:
    """Verify rescue necessity detection."""

    def test_good_permissions_no_rescue(self, tmp_path):
        key = tmp_path / "id_test"
        key.write_text("fake-key-content")
        os.chmod(str(key), 0o600)
        assert needs_rescue(key) is False

    def test_missing_file_no_rescue(self, tmp_path):
        missing = tmp_path / "nonexistent"
        assert needs_rescue(missing) is False

    def test_bad_but_fixable_no_rescue(self, tmp_path):
        """On a normal filesystem, chmod works, so rescue is not needed."""
        key = tmp_path / "id_test"
        key.write_text("fake-key-content")
        os.chmod(str(key), 0o777)
        # On tmpfs, chmod works, so needs_rescue should return False.
        assert needs_rescue(key) is False


# ---------------------------------------------------------------------------
# rescue_key
# ---------------------------------------------------------------------------

class TestRescueKey:
    """Verify the key copy and environment override."""

    def test_rescue_creates_copy(self, tmp_path):
        key = tmp_path / "id_test"
        key.write_text("fake-key-content-for-rescue")
        os.chmod(str(key), 0o777)

        with patch("iamai.ssh_key_rescue.RESCUE_DIR", tmp_path / "rescue"):
            with patch("iamai.ssh_key_rescue.RESCUE_KEY", tmp_path / "rescue" / "id_test"):
                env = rescue_key(key)
                rescue_path = tmp_path / "rescue" / "id_test"
                assert rescue_path.exists()
                assert rescue_path.read_text() == "fake-key-content-for-rescue"
                assert rescue_path.stat().st_mode & 0o777 == 0o600
                assert "GIT_SSH_COMMAND" in env
                assert str(rescue_path) in env["GIT_SSH_COMMAND"]

    def test_rescue_missing_key_raises(self, tmp_path):
        missing = tmp_path / "nonexistent"
        with pytest.raises(FileNotFoundError):
            rescue_key(missing)

    def test_rescue_idempotent(self, tmp_path):
        key = tmp_path / "id_test"
        key.write_text("same-content")

        rescue_dir = tmp_path / "rescue"
        rescue_file = rescue_dir / "id_test"

        with patch("iamai.ssh_key_rescue.RESCUE_DIR", rescue_dir):
            with patch("iamai.ssh_key_rescue.RESCUE_KEY", rescue_file):
                env1 = rescue_key(key)
                mtime1 = rescue_file.stat().st_mtime

                # Second call with same content should not re-copy.
                import time
                time.sleep(0.1)
                env2 = rescue_key(key)
                mtime2 = rescue_file.stat().st_mtime

                assert env1 == env2
                # mtime unchanged means no re-copy happened.
                assert mtime1 == mtime2


# ---------------------------------------------------------------------------
# rescue_env
# ---------------------------------------------------------------------------

class TestRescueEnv:
    """Verify full environment construction."""

    def test_rescue_env_includes_path(self):
        """When no rescue needed, returns a copy of current env."""
        env = rescue_env(DEFAULT_KEY_PATH)
        assert "PATH" in env
        assert isinstance(env, dict)

    def test_rescue_env_is_copy(self):
        """Modifying returned env must not affect os.environ."""
        env = rescue_env(DEFAULT_KEY_PATH)
        env["TEST_MARKER"] = "should_not_leak"
        assert "TEST_MARKER" not in os.environ
