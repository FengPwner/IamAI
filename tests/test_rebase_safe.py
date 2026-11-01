"""tests for rebase_safe — safe stash-rebase-push with live writer."""

import os
import signal
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from iamai.rebase_safe import (
    RebaseResult,
    find_writer_pid,
    sync,
    _is_dirty,
    _ahead_behind,
    _run,
)


# --- helpers ---

def _init_repo(tmpdir: str) -> str:
    """Create a minimal git repo with one commit on 'main'."""
    subprocess.run(["git", "init", "-b", "main", tmpdir],
                   capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", tmpdir, "config", "user.email", "test@test.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", tmpdir, "config", "user.name", "test"],
        capture_output=True, check=True,
    )
    readme = Path(tmpdir) / "README.md"
    readme.write_text("# test\n")
    subprocess.run(["git", "-C", tmpdir, "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", tmpdir, "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    return tmpdir


# --- RebaseResult ---

class TestRebaseResult:
    def test_frozen(self):
        r = RebaseResult(success=True, writer_pid=1, stashed=False,
                         rebased=False, pushed=True, stash_popped=False,
                         reason="ok")
        with pytest.raises(AttributeError):
            r.success = False  # type: ignore

    def test_fields(self):
        r = RebaseResult(success=False, writer_pid=None, stashed=True,
                         rebased=False, pushed=False, stash_popped=False,
                         reason="fetch failed")
        assert r.success is False
        assert r.writer_pid is None
        assert r.stashed is True
        assert r.reason == "fetch failed"


# --- _is_dirty ---

class TestIsDirty:
    def test_clean_repo(self, tmp_path):
        repo = _init_repo(str(tmp_path / "repo"))
        assert _is_dirty(repo) is False

    def test_dirty_repo(self, tmp_path):
        repo = _init_repo(str(tmp_path / "repo"))
        (Path(repo) / "dirty.txt").write_text("new")
        assert _is_dirty(repo) is True

    def test_staged_is_dirty(self, tmp_path):
        repo = _init_repo(str(tmp_path / "repo"))
        (Path(repo) / "staged.txt").write_text("s")
        subprocess.run(["git", "-C", repo, "add", "staged.txt"],
                       capture_output=True)
        assert _is_dirty(repo) is True


# --- _ahead_behind ---

class TestAheadBehind:
    def test_same_commit(self, tmp_path):
        repo = _init_repo(str(tmp_path / "repo"))
        # create a bare remote and push
        bare = str(tmp_path / "bare.git")
        subprocess.run(["git", "init", "--bare", bare],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin", bare],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", repo, "push", "-u", "origin", "main"],
                       capture_output=True, check=True)
        la, ra = _ahead_behind(repo, "origin", "main")
        assert la == 0
        assert ra == 0

    def test_local_ahead(self, tmp_path):
        repo = _init_repo(str(tmp_path / "repo"))
        bare = str(tmp_path / "bare.git")
        subprocess.run(["git", "init", "--bare", bare],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin", bare],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", repo, "push", "-u", "origin", "main"],
                       capture_output=True, check=True)
        # add a local commit without pushing
        (Path(repo) / "local.txt").write_text("local")
        subprocess.run(["git", "-C", repo, "add", "."], capture_output=True)
        subprocess.run(["git", "-C", repo, "commit", "-m", "local"],
                       capture_output=True)
        la, ra = _ahead_behind(repo, "origin", "main")
        assert la == 1
        assert ra == 0


# --- find_writer_pid ---

class TestFindWriterPid:
    def test_no_writer_running(self):
        pid = find_writer_pid("nonexistent_writer_xyz")
        assert pid is None

    @patch("iamai.rebase_safe._run")
    def test_found(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="12345\n"
        )
        pid = find_writer_pid("qwen")
        assert pid == 12345

    @patch("iamai.rebase_safe._run")
    def test_not_found_pgrep(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert find_writer_pid("qwen") is None

    @patch("iamai.rebase_safe._run")
    def test_bad_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="not_a_number\n"
        )
        assert find_writer_pid("qwen") is None


# --- sync: already in sync ---

class TestSyncAlreadyInSync:
    def test_nothing_to_do(self, tmp_path):
        repo = _init_repo(str(tmp_path / "repo"))
        bare = str(tmp_path / "bare.git")
        subprocess.run(["git", "init", "--bare", bare],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin", bare],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", repo, "push", "-u", "origin", "main"],
                       capture_output=True, check=True)

        result = sync(repo, writer_pid=None)
        assert result.success is True
        assert result.reason == "already in sync — nothing to do"
        assert result.stashed is False
        assert result.rebased is False


# --- sync: dry_run ---

class TestSyncDryRun:
    def test_dry_run_with_remote_ahead(self, tmp_path):
        repo = _init_repo(str(tmp_path / "repo"))
        bare = str(tmp_path / "bare.git")
        subprocess.run(["git", "init", "--bare", bare],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin", bare],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", repo, "push", "-u", "origin", "main"],
                       capture_output=True, check=True)

        # simulate remote getting ahead via a clone
        clone = str(tmp_path / "clone")
        subprocess.run(["git", "clone", "-b", "main", bare, clone],
                       capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", clone, "config", "user.email", "r@r.com"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", clone, "config", "user.name", "r"],
            capture_output=True,
        )
        (Path(clone) / "remote.txt").write_text("remote change")
        subprocess.run(["git", "-C", clone, "add", "."], capture_output=True)
        subprocess.run(["git", "-C", clone, "commit", "-m", "remote work"],
                       capture_output=True)
        subprocess.run(["git", "-C", clone, "push"], capture_output=True)

        # pass writer_pid=-1 (sentinel: don't auto-discover, don't pause)
        result = sync(repo, writer_pid=-1, dry_run=True)
        assert result.success is True
        assert "dry-run" in result.reason
        assert result.rebased is True  # remote is ahead


# --- sync: full flow ---

class TestSyncFullFlow:
    def test_rebase_and_push(self, tmp_path):
        """Local behind remote → rebase → push should succeed."""
        repo = _init_repo(str(tmp_path / "repo"))
        bare = str(tmp_path / "bare.git")
        subprocess.run(["git", "init", "--bare", bare],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin", bare],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", repo, "push", "-u", "origin", "main"],
                       capture_output=True, check=True)

        # push a commit from a clone to make remote ahead
        clone = str(tmp_path / "clone")
        subprocess.run(["git", "clone", "-b", "main", bare, clone],
                       capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", clone, "config", "user.email", "r@r.com"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", clone, "config", "user.name", "r"],
            capture_output=True,
        )
        (Path(clone) / "remote.txt").write_text("from remote")
        subprocess.run(["git", "-C", clone, "add", "."], capture_output=True)
        subprocess.run(["git", "-C", clone, "commit", "-m", "remote work"],
                       capture_output=True)
        subprocess.run(["git", "-C", clone, "push"], capture_output=True)

        result = sync(repo, writer_pid=None)  # None = no writer mgmt
        assert result.success is True
        assert result.rebased is True
        assert result.pushed is True

    def test_stash_dirty_then_sync(self, tmp_path):
        """Dirty working tree → stash → rebase → push → stash pop."""
        repo = _init_repo(str(tmp_path / "repo"))
        bare = str(tmp_path / "bare.git")
        subprocess.run(["git", "init", "--bare", bare],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin", bare],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", repo, "push", "-u", "origin", "main"],
                       capture_output=True, check=True)

        # make remote ahead
        clone = str(tmp_path / "clone")
        subprocess.run(["git", "clone", "-b", "main", bare, clone],
                       capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", clone, "config", "user.email", "r@r.com"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", clone, "config", "user.name", "r"],
            capture_output=True,
        )
        (Path(clone) / "remote.txt").write_text("from remote")
        subprocess.run(["git", "-C", clone, "add", "."], capture_output=True)
        subprocess.run(["git", "-C", clone, "commit", "-m", "remote work"],
                       capture_output=True)
        subprocess.run(["git", "-C", clone, "push"], capture_output=True)

        # dirty the local working tree (untracked file — won't conflict)
        (Path(repo) / "dirty.txt").write_text("local dirt")

        result = sync(repo, writer_pid=None)
        assert result.success is True
        assert result.stashed is True
        assert result.stash_popped is True
        # dirty file should still exist after stash pop
        assert (Path(repo) / "dirty.txt").read_text() == "local dirt"


# --- sync: writer pause/resume ---

class TestSyncWriterPause:
    @patch("iamai.rebase_safe.os.kill")
    def test_sigstop_and_sigcont(self, mock_kill, tmp_path):
        """Verify SIGSTOP before and SIGCONT after."""
        repo = _init_repo(str(tmp_path / "repo"))
        bare = str(tmp_path / "bare.git")
        subprocess.run(["git", "init", "--bare", bare],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin", bare],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", repo, "push", "-u", "origin", "main"],
                       capture_output=True, check=True)

        # make remote ahead so sync actually does work
        clone = str(tmp_path / "clone")
        subprocess.run(["git", "clone", "-b", "main", bare, clone],
                       capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", clone, "config", "user.email", "r@r.com"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", clone, "config", "user.name", "r"],
            capture_output=True,
        )
        (Path(clone) / "r.txt").write_text("r")
        subprocess.run(["git", "-C", clone, "add", "."], capture_output=True)
        subprocess.run(["git", "-C", clone, "commit", "-m", "r"],
                       capture_output=True)
        subprocess.run(["git", "-C", clone, "push"], capture_output=True)

        fake_pid = 99999
        result = sync(repo, writer_pid=fake_pid)

        calls = mock_kill.call_args_list
        signals_sent = [c.args[1] for c in calls]
        assert signal.SIGSTOP in signals_sent
        assert signal.SIGCONT in signals_sent
        assert result.success is True

    @patch("iamai.rebase_safe.os.kill")
    def test_writer_already_dead(self, mock_kill, tmp_path):
        """If writer PID is gone, SIGSTOP raises ProcessLookupError — graceful."""
        # Make os.kill raise for the first call (SIGSTOP)
        mock_kill.side_effect = ProcessLookupError
        repo = _init_repo(str(tmp_path / "repo"))
        bare = str(tmp_path / "bare.git")
        subprocess.run(["git", "init", "--bare", bare],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin", bare],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", repo, "push", "-u", "origin", "main"],
                       capture_output=True, check=True)

        # make remote ahead so we actually enter the try block
        clone = str(tmp_path / "clone")
        subprocess.run(["git", "clone", "-b", "main", bare, clone],
                       capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", clone, "config", "user.email", "r@r.com"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", clone, "config", "user.name", "r"],
            capture_output=True,
        )
        (Path(clone) / "x.txt").write_text("x")
        subprocess.run(["git", "-C", clone, "add", "."], capture_output=True)
        subprocess.run(["git", "-C", clone, "commit", "-m", "x"],
                       capture_output=True)
        subprocess.run(["git", "-C", clone, "push"], capture_output=True)

        result = sync(repo, writer_pid=88888)
        assert result.success is True
        # SIGCONT in finally should also handle ProcessLookupError gracefully
