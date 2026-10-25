"""Tests for tools/repo_drift.py CLI wrapper."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "tools" / "repo_drift.py"


class TestCliBasic:
    def test_help(self):
        result = subprocess.run(
            [sys.executable, str(CLI), "--help"],
            capture_output=True,
            text=True,
            cwd=str(REPO),
        )
        assert result.returncode == 0
        assert "drift" in result.stdout.lower()

    def test_json_output(self):
        result = subprocess.run(
            [sys.executable, str(CLI), "--json"],
            capture_output=True,
            text=True,
            cwd=str(REPO),
        )
        # Should parse as valid JSON
        data = json.loads(result.stdout)
        assert "status" in data
        assert "branch" in data

    def test_text_output(self):
        result = subprocess.run(
            [sys.executable, str(CLI)],
            capture_output=True,
            text=True,
            cwd=str(REPO),
        )
        # Should produce some output (a summary line)
        assert len(result.stdout.strip()) > 0

    def test_repo_flag(self):
        result = subprocess.run(
            [sys.executable, str(CLI), "--repo", str(REPO), "--json"],
            capture_output=True,
            text=True,
            cwd=str(REPO),
        )
        data = json.loads(result.stdout)
        assert "status" in data

    def test_fetch_flag(self):
        result = subprocess.run(
            [sys.executable, str(CLI), "--fetch", "--json"],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            timeout=30,
        )
        data = json.loads(result.stdout)
        assert "status" in data

    def test_exit_code_consistency(self):
        """Exit code 0 means safe to push, 1 means pull needed, 2 means error."""
        result = subprocess.run(
            [sys.executable, str(CLI), "--json"],
            capture_output=True,
            text=True,
            cwd=str(REPO),
        )
        data = json.loads(result.stdout)
        status = data["status"]
        # Just verify it exits with a valid code
        assert result.returncode in (0, 1, 2)
