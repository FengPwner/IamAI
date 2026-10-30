#!/usr/bin/env python3
"""Tests for push_divergence_detector.py."""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from push_divergence_detector import detect


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
    """Clone the bare repo and properly track main."""
    clone_d = tempfile.mkdtemp(prefix="clone-")
    run(f"git clone {remote_d} {clone_d}")
    run('git config user.email "remote@test.local"', cwd=clone_d)
    run('git config user.name "Remote"', cwd=clone_d)
    # ensure local main tracks origin/main
    run("git checkout -B main --track origin/main", cwd=clone_d)
    return clone_d


def add_commits(d, n, prefix="local"):
    for i in range(n):
        with open(os.path.join(d, f"{prefix}_{i}.txt"), "w") as f:
            f.write(f"{prefix} {i}\n")
        run(f"git add -A && git commit -m '{prefix} commit {i}'", cwd=d)


def cleanup(*dirs):
    for d in dirs:
        subprocess.run(f"rm -rf {d}", shell=True)


def test_no_divergence():
    d, remote = make_base_repo()
    try:
        result = detect(d)
        assert result["local_ahead"] == 0
        assert result["remote_ahead"] == 0
        assert result["diverged"] is False
        assert result["push_will_fail"] is False
        assert result["fix"] == "nothing to do"
        print("  PASS: no divergence")
    finally:
        cleanup(d, remote)


def test_local_ahead_only():
    d, remote = make_base_repo()
    try:
        add_commits(d, 3, "local")
        result = detect(d)
        assert result["local_ahead"] == 3, f"expected 3, got {result['local_ahead']}"
        assert result["remote_ahead"] == 0
        assert result["diverged"] is False
        assert result["push_will_fail"] is False
        assert "push" in result["fix"]
        print("  PASS: local ahead only")
    finally:
        cleanup(d, remote)


def test_remote_ahead_only():
    d, remote = make_base_repo()
    clone_d = None
    try:
        clone_d = make_second_clone(remote)
        add_commits(clone_d, 2, "remote")
        run("git push origin main", cwd=clone_d)

        run("git fetch origin", cwd=d)
        result = detect(d)
        assert result["local_ahead"] == 0
        assert result["remote_ahead"] == 2, f"expected 2, got {result['remote_ahead']}"
        assert result["diverged"] is False
        assert result["push_will_fail"] is False
        assert "pull" in result["fix"]
        print("  PASS: remote ahead only")
    finally:
        cleanup(d, remote, clone_d)


def test_diverged_push_will_fail():
    d, remote = make_base_repo()
    clone_d = None
    try:
        # local commits (not pushed)
        add_commits(d, 2, "local")

        # remote commits from another clone
        clone_d = make_second_clone(remote)
        add_commits(clone_d, 3, "remote")
        run("git push origin main", cwd=clone_d)

        # fetch so local sees remote divergence
        run("git fetch origin", cwd=d)
        result = detect(d)
        assert result["local_ahead"] == 2, f"expected 2, got {result['local_ahead']}"
        assert result["remote_ahead"] == 3, f"expected 3, got {result['remote_ahead']}"
        assert result["diverged"] is True
        assert result["push_will_fail"] is True
        assert "merge" in result["fix"]
        print("  PASS: diverged — push will fail")
    finally:
        cleanup(d, remote, clone_d)


if __name__ == "__main__":
    print("push_divergence_detector tests:")
    test_no_divergence()
    test_local_ahead_only()
    test_remote_ahead_only()
    test_diverged_push_will_fail()
    print("\nall tests passed.")
