#!/usr/bin/env python3
"""Tests for push_auto_merge.py — exercises the three divergence scenarios."""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from push_auto_merge import auto_merge


def run(cmd, cwd=None):
    subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, check=True)


def make_base_repo():
    """Create a bare remote + working repo with one shared commit on 'main'."""
    remote_d = tempfile.mkdtemp(prefix="bare-")
    run(f"git init --bare {remote_d}")

    d = tempfile.mkdtemp(prefix="work-")
    run(f"git clone {remote_d} {d}")
    run('git config user.email "test@test.local"', cwd=d)
    run('git config user.name "Test"', cwd=d)

    with open(os.path.join(d, "README.md"), "w") as f:
        f.write("# test\n")
    run("git add -A && git commit -m 'init'", cwd=d)
    run("git branch -M main", cwd=d)
    run("git push -u origin main", cwd=d)

    return d, remote_d


def make_second_clone(remote_d):
    """Clone the bare repo to simulate a second writer."""
    clone_d = tempfile.mkdtemp(prefix="clone-")
    run(f"git clone {remote_d} {clone_d}")
    run('git config user.email "remote@test.local"', cwd=clone_d)
    run('git config user.name "Remote"', cwd=clone_d)
    run("git checkout main", cwd=clone_d)
    return clone_d


def test_clean():
    """No divergence, nothing to do."""
    d, _ = make_base_repo()
    result = auto_merge(repo=d)
    assert result["strategy"] == "clean"
    assert result["error"] is None
    print("  PASS: clean — no divergence detected")


def test_remote_ahead_ff():
    """Remote is ahead, local should fast-forward."""
    d, remote_d = make_base_repo()
    clone = make_second_clone(remote_d)

    # Second clone pushes a new commit
    with open(os.path.join(clone, "note.md"), "w") as f:
        f.write("remote note\n")
    run("git add -A && git commit -m 'remote: note'", cwd=clone)
    run("git push origin main", cwd=clone)

    # Our local fetches (no local commits ahead)
    run("git fetch origin main", cwd=d)

    result = auto_merge(repo=d)
    assert result["strategy"] == "ff-only"
    assert result["merged"] is True
    assert result["error"] is None
    # Verify the note exists locally
    assert os.path.isfile(os.path.join(d, "note.md"))
    print("  PASS: remote-ahead — fast-forward merged cleanly")


def test_diverged_merge_theirs():
    """Both sides diverged: local has commits, remote has different commits."""
    d, remote_d = make_base_repo()
    clone = make_second_clone(remote_d)

    # Local makes a commit
    with open(os.path.join(d, "local.md"), "w") as f:
        f.write("local work\n")
    run("git add -A && git commit -m 'local: work'", cwd=d)

    # Remote makes a different commit
    with open(os.path.join(clone, "remote.md"), "w") as f:
        f.write("remote work\n")
    run("git add -A && git commit -m 'remote: work'", cwd=clone)
    run("git push origin main", cwd=clone)

    # Local fetches and sees divergence
    run("git fetch origin main", cwd=d)

    result = auto_merge(repo=d)
    assert result["diverged"] is True
    assert result["strategy"] == "merge-theirs"
    assert result["merged"] is True
    assert result["pushed"] is True
    assert result["error"] is None
    # Both files should exist after merge
    assert os.path.isfile(os.path.join(d, "local.md"))
    assert os.path.isfile(os.path.join(d, "remote.md"))
    print("  PASS: diverged — merge-theirs resolved and pushed")


def test_local_ahead_push_only():
    """Local is ahead, remote is clean — just push."""
    d, _ = make_base_repo()

    with open(os.path.join(d, "extra.md"), "w") as f:
        f.write("extra\n")
    run("git add -A && git commit -m 'local: extra'", cwd=d)

    result = auto_merge(repo=d)
    assert result["strategy"] == "push-only"
    assert result["pushed"] is True
    assert result["error"] is None
    print("  PASS: local-ahead — pushed without merge")


def test_dry_run_diverged():
    """Dry run should report strategy without acting."""
    d, remote_d = make_base_repo()
    clone = make_second_clone(remote_d)

    # Diverge
    with open(os.path.join(d, "a.md"), "w") as f:
        f.write("a\n")
    run("git add -A && git commit -m 'local: a'", cwd=d)

    with open(os.path.join(clone, "b.md"), "w") as f:
        f.write("b\n")
    run("git add -A && git commit -m 'remote: b'", cwd=clone)
    run("git push origin main", cwd=clone)
    run("git fetch origin main", cwd=d)

    result = auto_merge(repo=d, dry_run=True)
    assert result["diverged"] is True
    assert result["strategy"] == "merge-theirs"
    assert result["merged"] is False  # dry run should not merge
    assert result["pushed"] is False
    print("  PASS: dry-run — reported strategy without modifying repo")


def test_conflicting_file_theirs_wins():
    """Both sides modify the same file: -X theirs should pick remote version."""
    d, remote_d = make_base_repo()
    clone = make_second_clone(remote_d)

    # Both sides modify README.md differently
    with open(os.path.join(d, "README.md"), "w") as f:
        f.write("# test\n\nlocal modification\n")
    run("git add -A && git commit -m 'local: readme'", cwd=d)

    with open(os.path.join(clone, "README.md"), "w") as f:
        f.write("# test\n\nremote modification\n")
    run("git add -A && git commit -m 'remote: readme'", cwd=clone)
    run("git push origin main", cwd=clone)
    run("git fetch origin main", cwd=d)

    result = auto_merge(repo=d)
    assert result["diverged"] is True
    assert result["merged"] is True
    assert result["pushed"] is True
    assert result["error"] is None

    # Theirs (remote) should win on conflict
    content = open(os.path.join(d, "README.md")).read()
    assert "remote modification" in content
    print("  PASS: conflict — theirs strategy picked remote version")


if __name__ == "__main__":
    print("=== push_auto_merge tests ===")
    tests = [
        test_clean,
        test_remote_ahead_ff,
        test_diverged_merge_theirs,
        test_local_ahead_push_only,
        test_dry_run_diverged,
        test_conflicting_file_theirs_wins,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {t.__name__} — {e}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(1 if failed else 0)
