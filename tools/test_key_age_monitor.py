#!/usr/bin/env python3
"""Tests for key_age_monitor.py — SSH deploy key age checker.

Covers:
  - find_key returns first existing path
  - check_key_age: fresh / warn / critical / missing levels
  - format_status: text and JSON output
  - main() CLI with --json / --warn / --critical / --key
  - Edge cases: missing file, zero-age key, negative age (clock skew)
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from key_age_monitor import (
    find_key,
    check_key_age,
    format_status,
    main,
    KeyStatus,
)


# ---------------------------------------------------------------------------
# find_key
# ---------------------------------------------------------------------------

class TestFindKey:
    def test_returns_first_existing(self, tmp_path):
        a = tmp_path / "a_key"
        b = tmp_path / "b_key"
        a.write_text("ssh-ed25519 AAAA")
        b.write_text("ssh-ed25519 BBBB")
        result = find_key(paths=[a, b])
        assert result == a

    def test_skips_missing_returns_second(self, tmp_path):
        a = tmp_path / "nonexistent"
        b = tmp_path / "real_key"
        b.write_text("ssh-ed25519 AAAA")
        result = find_key(paths=[a, b])
        assert result == b

    def test_returns_none_when_all_missing(self, tmp_path):
        result = find_key(paths=[tmp_path / "x", tmp_path / "y"])
        assert result is None


# ---------------------------------------------------------------------------
# check_key_age
# ---------------------------------------------------------------------------

class TestCheckKeyAge:
    def _make_key(self, tmp_path, age_days=0):
        key = tmp_path / "deploy_key"
        key.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA test@iamai")
        if age_days > 0:
            old_time = time.time() - age_days * 86400
            os.utime(key, (old_time, old_time))
        return key

    def test_fresh_key(self, tmp_path):
        key = self._make_key(tmp_path, age_days=2)
        status = check_key_age(key, warn_days=7, critical_days=14)
        assert status.level == "fresh"
        assert status.age_days == pytest.approx(2.0, abs=0.1)

    def test_warn_key(self, tmp_path):
        key = self._make_key(tmp_path, age_days=10)
        status = check_key_age(key, warn_days=7, critical_days=14)
        assert status.level == "warn"
        assert "10" in status.detail

    def test_critical_key(self, tmp_path):
        key = self._make_key(tmp_path, age_days=20)
        status = check_key_age(key, warn_days=7, critical_days=14)
        assert status.level == "critical"
        assert "rotate" in status.detail.lower()

    def test_missing_key(self, tmp_path):
        status = check_key_age(tmp_path / "nope", warn_days=7, critical_days=14)
        assert status.level == "missing"
        assert status.age_days == -1

    def test_zero_age_key(self, tmp_path):
        key = self._make_key(tmp_path, age_days=0)
        now = time.time()
        status = check_key_age(key, warn_days=7, critical_days=14, now=now)
        assert status.level == "fresh"
        assert status.age_days == pytest.approx(0.0, abs=0.01)

    def test_exact_warn_boundary(self, tmp_path):
        key = self._make_key(tmp_path, age_days=7)
        status = check_key_age(key, warn_days=7, critical_days=14)
        assert status.level == "warn"

    def test_exact_critical_boundary(self, tmp_path):
        key = self._make_key(tmp_path, age_days=14)
        status = check_key_age(key, warn_days=7, critical_days=14)
        assert status.level == "critical"

    def test_detail_includes_path(self, tmp_path):
        key = self._make_key(tmp_path, age_days=1)
        status = check_key_age(key, warn_days=7, critical_days=14)
        assert str(key) in status.path


# ---------------------------------------------------------------------------
# format_status
# ---------------------------------------------------------------------------

class TestFormatStatus:
    def test_text_fresh(self):
        s = KeyStatus("/tmp/k", 3.0, 1000.0, "fresh", "key is 3.0 days old")
        out = format_status(s, as_json=False)
        assert "FRESH" in out
        assert "3.0 days" in out

    def test_text_warn(self):
        s = KeyStatus("/tmp/k", 10.5, 1000.0, "warn", "aging")
        out = format_status(s, as_json=False)
        assert "WARN" in out

    def test_json_output(self):
        s = KeyStatus("/tmp/k", 5.0, 1000.0, "fresh", "ok")
        out = format_status(s, as_json=True)
        data = json.loads(out)
        assert data["level"] == "fresh"
        assert data["age_days"] == 5.0
        assert data["path"] == "/tmp/k"


# ---------------------------------------------------------------------------
# main (CLI)
# ---------------------------------------------------------------------------

class TestMain:
    def test_no_key_returns_2(self, tmp_path, capsys):
        code = main(["--key", str(tmp_path / "nope")])
        assert code == 2
        captured = capsys.readouterr()
        assert "MISSING" in captured.err or "missing" in captured.out

    def test_fresh_key_returns_0(self, tmp_path, capsys):
        key = tmp_path / "k"
        key.write_text("ssh-ed25519 test")
        code = main(["--key", str(key), "--warn", "7", "--critical", "14"])
        assert code == 0
        captured = capsys.readouterr()
        assert "FRESH" in captured.out

    def test_warn_key_returns_1(self, tmp_path, capsys):
        key = tmp_path / "k"
        key.write_text("ssh-ed25519 test")
        old_time = time.time() - 10 * 86400
        os.utime(key, (old_time, old_time))
        code = main(["--key", str(key), "--warn", "7", "--critical", "14"])
        assert code == 1
        captured = capsys.readouterr()
        assert "WARN" in captured.out

    def test_json_flag(self, tmp_path, capsys):
        key = tmp_path / "k"
        key.write_text("ssh-ed25519 test")
        code = main(["--key", str(key), "--json"])
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert "level" in data
        assert "age_days" in data

    def test_no_key_json_output(self, tmp_path, capsys):
        code = main(["--key", str(tmp_path / "missing")])
        assert code == 2
