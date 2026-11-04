"""Tests for iamai.repo_meta_health — watcher-vs-watched ratio tracker."""

import pytest
from iamai.repo_meta_health import (
    MetaSnapshot,
    _classify_file,
    analyze,
    trend,
    meta_health_report,
    main,
)


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------

class TestClassifyFile:
    """_classify_file should bucket files correctly."""

    # Content
    def test_notes_file(self):
        assert _classify_file("notes/limits.md") == "content"

    def test_docs_metrics(self):
        assert _classify_file("docs/METRICS.md") == "content"

    def test_strokes_jsonl(self):
        assert _classify_file("data/strokes.jsonl") == "content"

    def test_snippets(self):
        assert _classify_file("snippets/pool.py") == "content"

    # Instrument
    def test_iamai_module(self):
        assert _classify_file("iamai/push_reliability.py") == "instrument"

    def test_test_file(self):
        assert _classify_file("tests/test_push_reliability.py") == "instrument"

    def test_scripts(self):
        assert _classify_file("scripts/deploy.sh") == "instrument"

    # Infra
    def test_tools_script(self):
        assert _classify_file("tools/run_both.sh") == "infra"

    def test_agent_dir(self):
        assert _classify_file("agent/qwen.md") == "infra"

    def test_makefile(self):
        assert _classify_file("Makefile") == "infra"

    def test_pytest_ini(self):
        assert _classify_file("pytest.ini") == "infra"

    def test_requirements(self):
        assert _classify_file("requirements-dev.txt") == "infra"

    def test_github_workflow(self):
        assert _classify_file(".github/workflows/ci.yml") == "infra"

    # Other
    def test_readme(self):
        assert _classify_file("README.md") == "other"

    def test_license(self):
        assert _classify_file("LICENSE") == "other"

    def test_gitignore(self):
        assert _classify_file(".gitignore") == "infra"


# ---------------------------------------------------------------------------
# MetaSnapshot
# ---------------------------------------------------------------------------

class TestMetaSnapshot:
    def test_empty_snapshot(self):
        snap = MetaSnapshot()
        assert snap.total == 0
        assert snap.meta_ratio == 0.0
        assert snap.verdict == "lean"

    def test_pure_content(self):
        snap = MetaSnapshot(content=100, instrument=0, infra=0, other=0, total=100)
        assert snap.meta_ratio == 0.0
        assert snap.verdict == "lean"

    def test_balanced(self):
        snap = MetaSnapshot(content=100, instrument=80, infra=10, other=10, total=200)
        assert snap.meta_ratio == 0.8
        assert snap.verdict == "balanced"

    def test_heavy(self):
        snap = MetaSnapshot(content=50, instrument=75, infra=10, other=5, total=140)
        assert snap.meta_ratio == 1.5
        assert snap.verdict == "heavy"

    def test_bloated(self):
        snap = MetaSnapshot(content=10, instrument=100, infra=5, other=5, total=120)
        assert snap.meta_ratio == 10.0
        assert snap.verdict == "bloated"

    def test_bucket_counts(self):
        snap = MetaSnapshot(content=10, instrument=20, infra=5, other=3, total=38)
        counts = snap.bucket_counts()
        assert counts == {"content": 10, "instrument": 20, "infra": 5, "other": 3}

    def test_summary_format(self):
        snap = MetaSnapshot(content=100, instrument=80, infra=10, other=10, total=200)
        s = snap.summary()
        assert "balanced" in s
        assert "0.80" in s
        assert "80 instrument" in s
        assert "100 content" in s

    def test_meta_ratio_zero_content(self):
        """No content files → denominator clamped to 1."""
        snap = MetaSnapshot(content=0, instrument=5, infra=0, other=0, total=5)
        assert snap.meta_ratio == 5.0
        assert snap.verdict == "bloated"


# ---------------------------------------------------------------------------
# analyze (with injected file list)
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_mixed_files(self):
        files = [
            "notes/limits.md",
            "docs/METRICS.md",
            "iamai/push.py",
            "iamai/stall_classifier.py",
            "tests/test_push.py",
            "tools/run_both.sh",
            "README.md",
            "LICENSE",
        ]
        snap = analyze(".", files=files)
        assert snap.content == 2
        assert snap.instrument == 3
        assert snap.infra == 1
        assert snap.other == 2
        assert snap.total == 8

    def test_all_content(self):
        files = [f"notes/n{i}.md" for i in range(10)]
        snap = analyze(".", files=files)
        assert snap.content == 10
        assert snap.instrument == 0
        assert snap.verdict == "lean"

    def test_all_instrument(self):
        files = [f"iamai/mod{i}.py" for i in range(10)]
        snap = analyze(".", files=files)
        assert snap.instrument == 10
        assert snap.content == 0
        assert snap.verdict == "bloated"

    def test_empty_list(self):
        snap = analyze(".", files=[])
        assert snap.total == 0
        assert snap.verdict == "lean"


# ---------------------------------------------------------------------------
# trend
# ---------------------------------------------------------------------------

class TestTrend:
    def test_improving(self):
        e = MetaSnapshot(content=100, instrument=80, infra=0, other=0, total=180)
        l = MetaSnapshot(content=120, instrument=70, infra=0, other=0, total=190)
        assert trend(e, l) == "improving"

    def test_worsening(self):
        e = MetaSnapshot(content=100, instrument=50, infra=0, other=0, total=150)
        l = MetaSnapshot(content=100, instrument=90, infra=0, other=0, total=190)
        assert trend(e, l) == "worsening"

    def test_stable(self):
        e = MetaSnapshot(content=100, instrument=80, infra=0, other=0, total=180)
        l = MetaSnapshot(content=100, instrument=82, infra=0, other=0, total=182)
        assert trend(e, l) == "stable"

    def test_stable_when_identical(self):
        s = MetaSnapshot(content=100, instrument=80, infra=10, other=10, total=200)
        assert trend(s, s) == "stable"

    def test_improving_large_shift(self):
        e = MetaSnapshot(content=50, instrument=100, infra=0, other=0, total=150)
        l = MetaSnapshot(content=100, instrument=100, infra=0, other=0, total=200)
        assert trend(e, l) == "improving"


# ---------------------------------------------------------------------------
# main (smoke test)
# ---------------------------------------------------------------------------

class TestMain:
    def test_main_runs(self, capsys):
        """main() should print without crashing."""
        main(".")
        out = capsys.readouterr().out
        assert "instrument" in out or "content" in out
