"""Tests for tools/pre_push_sync.py"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from pre_push_sync import (
    SyncResult,
    has_diverged,
    has_dirty_files,
    sync,
    get_local_sha,
    get_remote_sha,
    get_merge_base,
)


def _ok(stdout="", stderr=""):
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    m.stderr = stderr
    return m


def _fail(stderr=""):
    m = MagicMock()
    m.returncode = 1
    m.stdout = ""
    m.stderr = stderr
    return m


class TestGetShas:
    @patch("pre_push_sync.run")
    def test_local_sha_success(self, mock_run):
        mock_run.return_value = _ok("abc123\n")
        assert get_local_sha(Path("/tmp"), "main") == "abc123"

    @patch("pre_push_sync.run")
    def test_local_sha_failure(self, mock_run):
        mock_run.return_value = _fail()
        assert get_local_sha(Path("/tmp"), "main") == ""

    @patch("pre_push_sync.run")
    def test_remote_sha_success(self, mock_run):
        mock_run.return_value = _ok("def456\n")
        assert get_remote_sha(Path("/tmp"), "origin", "main") == "def456"

    @patch("pre_push_sync.run")
    def test_merge_base_success(self, mock_run):
        mock_run.return_value = _ok("base789\n")
        assert get_merge_base(Path("/tmp"), "abc", "def") == "base789"


class TestHasDiverged:
    @patch("pre_push_sync.run")
    def test_no_divergence_same_sha(self, mock_run):
        mock_run.return_value = _ok("abc123\n")
        assert has_diverged(Path("/tmp")) is False

    @patch("pre_push_sync.get_merge_base")
    @patch("pre_push_sync.get_remote_sha")
    @patch("pre_push_sync.get_local_sha")
    def test_no_divergence_fast_forward(self, mock_local, mock_remote, mock_base):
        mock_local.return_value = "abc"
        mock_remote.return_value = "def"
        mock_base.return_value = "abc"  # base == local means remote is ahead, not diverged
        assert has_diverged(Path("/tmp")) is False

    @patch("pre_push_sync.get_merge_base")
    @patch("pre_push_sync.get_remote_sha")
    @patch("pre_push_sync.get_local_sha")
    def test_diverged(self, mock_local, mock_remote, mock_base):
        mock_local.return_value = "abc"
        mock_remote.return_value = "def"
        mock_base.return_value = "older"  # base != local means true divergence
        assert has_diverged(Path("/tmp")) is True

    @patch("pre_push_sync.get_remote_sha")
    @patch("pre_push_sync.get_local_sha")
    def test_no_divergence_missing_sha(self, mock_local, mock_remote):
        mock_local.return_value = ""
        mock_remote.return_value = "def"
        assert has_diverged(Path("/tmp")) is False


class TestHasDirtyFiles:
    @patch("pre_push_sync.run")
    def test_clean(self, mock_run):
        mock_run.return_value = _ok("")
        assert has_dirty_files(Path("/tmp")) is False

    @patch("pre_push_sync.run")
    def test_dirty(self, mock_run):
        mock_run.return_value = _ok(" M file.txt\n")
        assert has_dirty_files(Path("/tmp")) is True


class TestSync:
    @patch("pre_push_sync.run")
    def test_fetch_failure(self, mock_run):
        mock_run.return_value = _fail("fatal: could not resolve host")
        result = sync(Path("/tmp"))
        assert result.ready is False
        assert "fetch failed" in result.message

    @patch("pre_push_sync.has_diverged")
    @patch("pre_push_sync.run")
    def test_no_divergence(self, mock_run, mock_diverged):
        # First call is fetch (success), then has_diverged returns False
        mock_run.return_value = _ok()
        mock_diverged.return_value = False
        result = sync(Path("/tmp"))
        assert result.ready is True
        assert "no divergence" in result.message

    @patch("pre_push_sync.has_dirty_files")
    @patch("pre_push_sync.has_diverged")
    @patch("pre_push_sync.run")
    def test_diverged_clean_merge(self, mock_run, mock_diverged, mock_dirty):
        mock_diverged.return_value = True
        mock_dirty.return_value = False

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "fetch"]:
                return _ok()
            if cmd[:2] == ["git", "pull"]:
                return _ok("Merge made by the 'ort' strategy.")
            return _ok()

        mock_run.side_effect = side_effect
        result = sync(Path("/tmp"))
        assert result.diverged is True
        assert result.merged is True
        assert result.stashed is False
        assert result.ready is True

    @patch("pre_push_sync.has_dirty_files")
    @patch("pre_push_sync.has_diverged")
    @patch("pre_push_sync.run")
    def test_diverged_dirty_full_cycle(self, mock_run, mock_diverged, mock_dirty):
        mock_diverged.return_value = True
        mock_dirty.return_value = True

        call_log = []

        def side_effect(cmd, **kwargs):
            call_log.append(cmd)
            if cmd[:2] == ["git", "fetch"]:
                return _ok()
            if cmd[:2] == ["git", "stash"] and "pop" not in cmd:
                return _ok("Saved working directory")
            if cmd[:2] == ["git", "pull"]:
                return _ok("Merge made by the 'ort' strategy.")
            if cmd[:3] == ["git", "stash", "pop"]:
                return _ok("On branch main")
            return _ok()

        mock_run.side_effect = side_effect
        result = sync(Path("/tmp"))
        assert result.diverged is True
        assert result.stashed is True
        assert result.merged is True
        assert result.stash_popped is True
        assert result.ready is True

    @patch("pre_push_sync.has_dirty_files")
    @patch("pre_push_sync.has_diverged")
    @patch("pre_push_sync.run")
    def test_diverged_merge_failure_aborts(self, mock_run, mock_diverged, mock_dirty):
        mock_diverged.return_value = True
        mock_dirty.return_value = False

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "fetch"]:
                return _ok()
            if cmd[:2] == ["git", "pull"]:
                return _fail("CONFLICT (content): Merge conflict in file.txt")
            if cmd[:2] == ["git", "merge"]:
                return _ok()
            return _ok()

        mock_run.side_effect = side_effect
        result = sync(Path("/tmp"))
        assert result.ready is False
        assert "merge failed" in result.message

    @patch("pre_push_sync.has_diverged")
    @patch("pre_push_sync.run")
    def test_dry_run(self, mock_run, mock_diverged):
        mock_diverged.return_value = True
        mock_run.return_value = _ok()  # fetch succeeds
        result = sync(Path("/tmp"), dry_run=True)
        assert result.diverged is True
        assert result.ready is False
        assert "dry-run" in result.message
