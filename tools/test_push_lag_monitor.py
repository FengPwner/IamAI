#!/usr/bin/env python3
"""Tests for push_lag_monitor.py"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from push_lag_monitor import (
    PushLag,
    measure_lag,
    get_commit_ts,
    get_commit_sha,
    count_unpushed,
    _fmt_ts,
    main,
)


def _init_repo(tmpdir: Path) -> Path:
    """Create a minimal git repo with a few commits."""
    repo = tmpdir / "test_repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=repo, capture_output=True)

    # Create a file and commit it
    (repo / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, capture_output=True, check=True)

    return repo


def _create_bare_remote(tmpdir: Path, repo: Path) -> None:
    """Create a bare clone as 'origin' and add it as a remote."""
    bare = tmpdir / "origin.git"
    subprocess.run(["git", "init", "--bare", str(bare)],
                   capture_output=True, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)],
                   cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "push", "origin", "main"],
                   cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "fetch", "origin"],
                   cwd=repo, capture_output=True, check=True)


def test_pushlag_creation_nominal():
    lag = PushLag("abc123def456", "abc123def456", 1000.0, 999.0, 0)
    assert lag.category == PushLag.NOMINAL
    assert lag.lag_seconds == 1.0
    assert lag.unpushed_count == 0
    print("  pass: pushlag_creation_nominal")


def test_pushlag_creation_warning():
    lag = PushLag("abc123def456", "abc123def456", 1000.0, 300.0, 5,
                  warning_threshold=600, critical_threshold=1800)
    assert lag.category == PushLag.WARNING
    assert lag.lag_seconds == 700.0
    print("  pass: pushlag_creation_warning")


def test_pushlag_creation_critical():
    lag = PushLag("abc123def456", "abc123def456", 2000.0, 100.0, 20,
                  warning_threshold=600, critical_threshold=1800)
    assert lag.category == PushLag.CRITICAL
    assert lag.lag_seconds == 1900.0
    print("  pass: pushlag_creation_critical")


def test_pushlag_zero_lag():
    lag = PushLag("abc123", "abc123", 1000.0, 1000.0, 0)
    assert lag.lag_seconds == 0.0
    assert lag.category == PushLag.NOMINAL
    print("  pass: pushlag_zero_lag")


def test_pushlag_negative_clamps():
    """If remote is ahead of local, lag should be 0."""
    lag = PushLag("abc123", "def456", 500.0, 1000.0, 0)
    assert lag.lag_seconds == 0.0
    print("  pass: pushlag_negative_clamps")


def test_pushlag_to_dict():
    lag = PushLag("abcdef123456", "abcdef123456", 1000.5, 999.0, 3)
    d = lag.to_dict()
    assert d["local_sha"] == "abcdef123456"
    assert d["remote_sha"] == "abcdef123456"
    assert d["lag_seconds"] == 1.5
    assert d["unpushed_count"] == 3
    assert d["category"] == "nominal"
    print("  pass: pushlag_to_dict")


def test_pushlag_format_report():
    lag = PushLag("abcdef123456789", "abcdef123456789", 1000.0, 300.0, 5,
                  warning_threshold=600, critical_threshold=1800)
    report = lag.format_report()
    assert "warning" in report.lower()
    assert "unpushed: 5" in report.lower()
    print("  pass: pushlag_format_report")


def test_pushlag_format_report_short_lag():
    lag = PushLag("abc123", "abc123", 1000.0, 970.0, 1)
    report = lag.format_report()
    assert "30s" in report
    print("  pass: pushlag_format_report_short_lag")


def test_pushlag_format_report_minutes_lag():
    lag = PushLag("abc123", "abc123", 1000.0, 400.0, 5,
                  warning_threshold=600)
    report = lag.format_report()
    assert "10.0m" in report
    print("  pass: pushlag_format_report_minutes_lag")


def test_pushlag_format_report_hours_lag():
    lag = PushLag("abc123", "abc123", 7200.0, 0.0, 50,
                  warning_threshold=600, critical_threshold=1800)
    report = lag.format_report()
    assert "2.0h" in report
    print("  pass: pushlag_format_report_hours_lag")


def test_pushlag_no_remote():
    lag = PushLag("abc123", "", 1000.0, 0.0, 0)
    assert lag.category == PushLag.WARNING  # 1000s > 600s warning, < 1800s critical
    d = lag.to_dict()
    assert d["remote_sha"] == "none"
    print("  pass: pushlag_no_remote")


def test_fmt_ts():
    ts = 1698000000.0  # 2023-10-22 16:00:00 UTC
    formatted = _fmt_ts(ts)
    assert "2023-10-22" in formatted
    assert "UTC" in formatted
    print("  pass: fmt_ts")


def test_fmt_ts_zero():
    assert _fmt_ts(0.0) == "never"
    print("  pass: fmt_ts_zero")


def test_get_commit_sha():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _init_repo(Path(tmpdir))
        sha = get_commit_sha(repo, "HEAD")
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)
        print("  pass: get_commit_sha")


def test_get_commit_sha_invalid():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _init_repo(Path(tmpdir))
        sha = get_commit_sha(repo, "nonexistent")
        assert sha == ""
        print("  pass: get_commit_sha_invalid")


def test_get_commit_ts():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _init_repo(Path(tmpdir))
        ts = get_commit_ts(repo, "HEAD")
        assert ts > 0
        print("  pass: get_commit_ts")


def test_count_unpushed_no_remote():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _init_repo(Path(tmpdir))
        count = count_unpushed(repo)
        assert count == 0  # no remote = no unpushed
        print("  pass: count_unpushed_no_remote")


def test_count_unpushed_with_remote():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _init_repo(Path(tmpdir))
        _create_bare_remote(Path(tmpdir), repo)

        # Add another local commit
        (repo / "new.txt").write_text("hello\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "second"], cwd=repo, capture_output=True, check=True)

        count = count_unpushed(repo)
        assert count == 1, f"expected 1 unpushed, got {count}"
        print("  pass: count_unpushed_with_remote")


def test_measure_lag_end_to_end():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _init_repo(Path(tmpdir))
        _create_bare_remote(Path(tmpdir), repo)

        # Push to sync
        subprocess.run(["git", "push", "origin", "main"],
                       cwd=repo, capture_output=True, check=True)

        lag = measure_lag(repo, warning_threshold=600, critical_threshold=1800)
        assert lag.category == PushLag.NOMINAL
        assert lag.unpushed_count == 0
        print("  pass: measure_lag_end_to_end")


def test_measure_lag_with_drift():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _init_repo(Path(tmpdir))
        _create_bare_remote(Path(tmpdir), repo)

        # Don't push — add more local commits
        for i in range(3):
            (repo / f"file_{i}.txt").write_text(f"content {i}\n")
            subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", f"local {i}"],
                           cwd=repo, capture_output=True, check=True)

        lag = measure_lag(repo, warning_threshold=600, critical_threshold=1800)
        assert lag.unpushed_count == 3
        print("  pass: measure_lag_with_drift")


def test_main_json_output():
    """Test main() with --json flag using this repo itself."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _init_repo(Path(tmpdir))
        _create_bare_remote(Path(tmpdir), repo)
        subprocess.run(["git", "push", "origin", "main"],
                       cwd=repo, capture_output=True, check=True)

        # Capture stdout
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            rc = main(["--repo", str(repo), "--json"])

        output = f.getvalue()
        data = json.loads(output)
        assert "lag_seconds" in data
        assert data["category"] in ("nominal", "warning", "critical")
        print("  pass: main_json_output")


def test_main_human_output():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _init_repo(Path(tmpdir))
        _create_bare_remote(Path(tmpdir), repo)
        subprocess.run(["git", "push", "origin", "main"],
                       cwd=repo, capture_output=True, check=True)

        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            rc = main(["--repo", str(repo), "--writer", "test"])

        output = f.getvalue()
        assert "test" in output
        assert "push lag" in output.lower()
        assert rc == 0
        print("  pass: main_human_output")


if __name__ == "__main__":
    tests = [
        test_pushlag_creation_nominal,
        test_pushlag_creation_warning,
        test_pushlag_creation_critical,
        test_pushlag_zero_lag,
        test_pushlag_negative_clamps,
        test_pushlag_to_dict,
        test_pushlag_format_report,
        test_pushlag_format_report_short_lag,
        test_pushlag_format_report_minutes_lag,
        test_pushlag_format_report_hours_lag,
        test_pushlag_no_remote,
        test_fmt_ts,
        test_fmt_ts_zero,
        test_get_commit_sha,
        test_get_commit_sha_invalid,
        test_get_commit_ts,
        test_count_unpushed_no_remote,
        test_count_unpushed_with_remote,
        test_measure_lag_end_to_end,
        test_measure_lag_with_drift,
        test_main_json_output,
        test_main_human_output,
    ]

    passed = 0
    failed = 0
    print(f"running {len(tests)} tests...\n")

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test.__name__}: {e}")
            failed += 1

    print(f"\n{passed}/{len(tests)} passed, {failed} failed")
    sys.exit(1 if failed else 0)
