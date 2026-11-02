"""
test_push_divergence_detection.py

Tests for detecting when a git push is rejected due to remote divergence,
and automatically triggering a rebase-and-retry cycle.

This is the missing piece identified across caretaker visits 489-498:
every single visit required manual stash -> pull --rebase -> stash pop -> push.
A divergence detector in the batch committer would eliminate this entirely.
"""

import subprocess
import tempfile
import os
from pathlib import Path

GIT_ENV = os.environ.copy()
GIT_ENV["GIT_CONFIG_COUNT"] = "1"
GIT_ENV["GIT_CONFIG_KEY_0"] = "init.defaultBranch"
GIT_ENV["GIT_CONFIG_VALUE_0"] = "main"


def run(cmd, cwd=None, check=True):
    """Run a shell command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd, shell=True, cwd=cwd,
        capture_output=True, text=True, env=GIT_ENV
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {cmd}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    return result.returncode, result.stdout, result.stderr


def setup_remote_with_seed(tmpdir):
    """Create a bare origin and seed it with one commit. Returns origin path."""
    origin = Path(tmpdir) / "origin.git"
    run(f"git init --bare {origin}")

    seed = Path(tmpdir) / "seed"
    run(f"git init {seed}")
    run("git config user.email seed@test.com", cwd=seed)
    run("git config user.name seed", cwd=seed)
    (seed / "file.txt").write_text("initial\n")
    run("git add .", cwd=seed)
    run('git commit -m "initial"', cwd=seed)
    run(f"git remote add origin {origin}", cwd=seed)
    run("git push -u origin main", cwd=seed)
    return origin


def test_push_rejection_detected():
    """A push to a diverged remote should be detected as a divergence event,
    not silently swallowed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        origin = setup_remote_with_seed(tmpdir)

        # Clone A
        local_a = Path(tmpdir) / "local_a"
        run(f"git clone {origin} {local_a}")
        run("git config user.email a@test.com", cwd=local_a)
        run("git config user.name a", cwd=local_a)

        # Clone B advances remote
        local_b = Path(tmpdir) / "local_b"
        run(f"git clone {origin} {local_b}")
        run("git config user.email b@test.com", cwd=local_b)
        run("git config user.name b", cwd=local_b)
        (local_b / "other.txt").write_text("remote advance\n")
        run("git add .", cwd=local_b)
        run('git commit -m "remote advance"', cwd=local_b)
        run("git push origin main", cwd=local_b)

        # local_a diverges
        (local_a / "divergent.txt").write_text("local work\n")
        run("git add .", cwd=local_a)
        run('git commit -m "local divergent work"', cwd=local_a)

        rc, stdout, stderr = run(
            "git push origin main", cwd=local_a, check=False
        )
        combined = stdout + stderr

        assert rc != 0, "Push should fail when remote has diverged"
        assert "rejected" in combined.lower(), (
            f"Expected 'rejected' in push output, got: {combined}"
        )
        assert "fetch first" in combined.lower() or "non-fast-forward" in combined.lower(), (
            f"Expected divergence signal in output, got: {combined}"
        )


def test_rebase_resolves_divergence():
    """After detecting divergence, stash + rebase + pop should resolve it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        origin = setup_remote_with_seed(tmpdir)

        local_a = Path(tmpdir) / "local_a"
        run(f"git clone {origin} {local_a}")
        run("git config user.email a@test.com", cwd=local_a)
        run("git config user.name a", cwd=local_a)

        local_b = Path(tmpdir) / "local_b"
        run(f"git clone {origin} {local_b}")
        run("git config user.email b@test.com", cwd=local_b)
        run("git config user.name b", cwd=local_b)
        (local_b / "other.txt").write_text("remote advance\n")
        run("git add .", cwd=local_b)
        run('git commit -m "remote advance"', cwd=local_b)
        run("git push origin main", cwd=local_b)

        # Local divergent commit
        (local_a / "divergent.txt").write_text("local work\n")
        run("git add .", cwd=local_a)
        run('git commit -m "local divergent work"', cwd=local_a)
        # Unstaged change from live writer (modify a tracked file)
        (local_a / "file.txt").write_text("writer is still writing\n")

        # Divergence recovery: stash -> rebase -> pop
        run("git stash", cwd=local_a)
        run("git pull --rebase origin main", cwd=local_a)
        run("git stash pop", cwd=local_a)

        rc, _, _ = run("git push origin main", cwd=local_a, check=False)
        assert rc == 0, "Push should succeed after rebase"

        # Verify both commits are in the remote
        run("git pull origin main", cwd=local_b)
        log_out = subprocess.check_output(
            "git log --oneline", shell=True, cwd=local_b, text=True
        )
        assert "remote advance" in log_out
        assert "local divergent work" in log_out


def test_divergence_detection_function():
    """A standalone function that wraps the divergence detection logic,
    suitable for integration into the batch committer."""

    def is_push_diverged(stderr_text: str) -> bool:
        """Return True if git push stderr indicates remote divergence."""
        lower = stderr_text.lower()
        divergence_signals = [
            "rejected",
            "fetch first",
            "non-fast-forward",
            "updates were rejected",
        ]
        return any(signal in lower for signal in divergence_signals)

    # Positive cases
    assert is_push_diverged(
        "! [rejected]        main -> main (fetch first)\n"
        "error: failed to push some refs\n"
        "hint: Updates were rejected because the remote contains work"
    )
    assert is_push_diverged(
        "To github.com:user/repo.git\n"
        " ! [rejected]  HEAD -> main (non-fast-forward)\n"
    )

    # Negative cases
    assert not is_push_diverged(
        "Enumerating objects: 5, done.\n"
        "To github.com:user/repo.git\n"
        "   abc1234..def5678  main -> main\n"
    )
    assert not is_push_diverged("")


if __name__ == "__main__":
    test_push_rejection_detected()
    test_rebase_resolves_divergence()
    test_divergence_detection_function()
    print("All divergence detection tests passed.")
