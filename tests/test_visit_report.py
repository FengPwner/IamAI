"""Tests for iamai.visit_report — caretaker visit report generation."""

import pytest

from iamai.visit_report import (
    Action,
    Finding,
    Metrics,
    VisitReport,
    classify_severity,
    distribution_label_full,
    format_gap,
    stroke_distribution_label,
)


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


class TestFinding:
    def test_default_severity(self):
        f = Finding("all good")
        assert f.severity == "info"

    def test_icon_info(self):
        assert Finding("x", severity="info").icon == "ℹ️"

    def test_icon_warning(self):
        assert Finding("x", severity="warning").icon == "⚠️"

    def test_icon_critical(self):
        assert Finding("x", severity="critical").icon == "🔴"

    def test_invalid_severity_raises(self):
        with pytest.raises(ValueError, match="finding severity"):
            Finding("bad", severity="extreme")

    def test_render_info(self):
        f = Finding("writer running", severity="info")
        assert f.render() == "- ℹ️ writer running"

    def test_render_critical(self):
        f = Finding("process dead", severity="critical")
        assert f.render() == "- 🔴 process dead"

    def test_render_preserves_text(self):
        desc = "9 uncommitted files in staging area"
        assert desc in Finding(desc, severity="warning").render()


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------


class TestAction:
    def test_default_success(self):
        a = Action("restarted writer")
        assert a.success is True

    def test_icon_success(self):
        assert Action("ok", success=True).icon == "✅"

    def test_icon_failure(self):
        assert Action("fail", success=False).icon == "❌"

    def test_render_with_index(self):
        a = Action("committed backlog", success=True)
        assert a.render(1) == "1. ✅ committed backlog"

    def test_render_with_detail(self):
        a = Action("restarted", success=True, detail="pid 1467")
        result = a.render(3)
        assert result == "3. ✅ restarted — pid 1467"

    def test_render_failure(self):
        a = Action("rebase failed", success=False)
        assert a.render(2) == "2. ❌ rebase failed"

    def test_render_failure_with_detail(self):
        a = Action("push", success=False, detail="conflict on main")
        result = a.render(1)
        assert "❌ push" in result
        assert "conflict on main" in result


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_defaults(self):
        m = Metrics()
        assert m.total_strokes == 0
        assert m.writer_running is False

    def test_writer_icon_running(self):
        assert Metrics(writer_running=True).writer_icon == "🟢"

    def test_writer_icon_stopped(self):
        assert Metrics(writer_running=False).writer_icon == "🔴"

    def test_batch_icon_running(self):
        assert Metrics(batch_running=True).batch_icon == "🟢"

    def test_batch_icon_stopped(self):
        assert Metrics(batch_running=False).batch_icon == "🔴"

    def test_backlog_cleared_true(self):
        m = Metrics(uncommitted_before=9, uncommitted_after=0)
        assert m.backlog_cleared is True

    def test_backlog_cleared_false_still_pending(self):
        m = Metrics(uncommitted_before=9, uncommitted_after=3)
        assert m.backlog_cleared is False

    def test_backlog_cleared_false_no_backlog(self):
        m = Metrics(uncommitted_before=0, uncommitted_after=0)
        assert m.backlog_cleared is False

    def test_render_table_basic(self):
        m = Metrics(total_strokes=100, total_files=50, total_commits=25)
        lines = m.render_table()
        assert any("100" in line for line in lines)
        assert any("50" in line for line in lines)
        assert any("25" in line for line in lines)

    def test_render_table_shows_backlog_clear(self):
        m = Metrics(uncommitted_before=5, uncommitted_after=0)
        lines = m.render_table()
        assert any("cleared" in line for line in lines)

    def test_render_table_includes_gap(self):
        m = Metrics(gap_seconds=2682)
        lines = m.render_table()
        assert any("44m 42s" in line for line in lines)

    def test_render_table_no_gap(self):
        m = Metrics(gap_seconds=0)
        lines = m.render_table()
        assert not any("Last gap" in line for line in lines)

    def test_render_table_extra(self):
        m = Metrics(extra={"python_files": 450, "logged_thoughts": 2910})
        lines = m.render_table()
        assert any("python_files" in line for line in lines)
        assert any("2910" in line for line in lines)

    def test_render_table_includes_process_status(self):
        m = Metrics(writer_running=True, batch_running=False)
        lines = m.render_table()
        # writer green, batch red
        assert any("🟢" in line and "🔴" in line for line in lines)


# ---------------------------------------------------------------------------
# classify_severity
# ---------------------------------------------------------------------------


class TestClassifySeverity:
    def test_healthy_no_issues(self):
        assert classify_severity([], []) == "healthy"

    def test_healthy_info_only(self):
        findings = [Finding("writer up", severity="info")]
        assert classify_severity(findings, []) == "healthy"

    def test_recovered_critical_all_ok(self):
        findings = [Finding("dead", severity="critical")]
        actions = [Action("restart", success=True)]
        assert classify_severity(findings, actions) == "recovered"

    def test_degraded_critical_action_failed(self):
        findings = [Finding("dead", severity="critical")]
        actions = [Action("restart", success=False)]
        assert classify_severity(findings, actions) == "degraded"

    def test_recovered_warning_all_ok(self):
        findings = [Finding("backlog", severity="warning")]
        actions = [Action("commit", success=True)]
        assert classify_severity(findings, actions) == "recovered"

    def test_degraded_warning_action_failed(self):
        findings = [Finding("backlog", severity="warning")]
        actions = [Action("commit", success=False)]
        assert classify_severity(findings, actions) == "degraded"

    def test_healthy_no_findings_no_actions(self):
        assert classify_severity([], []) == "healthy"

    def test_mixed_severities_all_ok(self):
        findings = [
            Finding("info thing", severity="info"),
            Finding("warn thing", severity="warning"),
            Finding("crit thing", severity="critical"),
        ]
        actions = [Action("fixed", success=True)]
        assert classify_severity(findings, actions) == "recovered"

    def test_mixed_severities_partial_fail(self):
        findings = [
            Finding("warn thing", severity="warning"),
            Finding("crit thing", severity="critical"),
        ]
        actions = [
            Action("fixed warn", success=True),
            Action("fixed crit", success=False),
        ]
        assert classify_severity(findings, actions) == "degraded"


# ---------------------------------------------------------------------------
# format_gap
# ---------------------------------------------------------------------------


class TestFormatGap:
    def test_seconds_only(self):
        assert format_gap(45) == "45s"

    def test_minutes_and_seconds(self):
        assert format_gap(130) == "2m 10s"

    def test_exact_minutes(self):
        assert format_gap(600) == "10m 0s"

    def test_hours(self):
        assert format_gap(3661) == "1h 1m"

    def test_zero(self):
        assert format_gap(0) == "0s"

    def test_large_gap(self):
        assert format_gap(7200) == "2h 0m"

    def test_59_seconds(self):
        assert format_gap(59) == "59s"

    def test_exactly_one_hour(self):
        assert format_gap(3600) == "1h 0m"


# ---------------------------------------------------------------------------
# stroke_distribution_label
# ---------------------------------------------------------------------------


class TestStrokeDistributionLabel:
    def test_single_category(self):
        assert stroke_distribution_label(100, 1) == "n/a"

    def test_zero_total(self):
        assert stroke_distribution_label(0, 5) == "n/a"

    def test_zero_categories(self):
        assert stroke_distribution_label(100, 0) == "n/a"

    def test_normal(self):
        result = stroke_distribution_label(400, 6)
        assert result in ("balanced", "skewed", "unbalanced")


# ---------------------------------------------------------------------------
# distribution_label_full
# ---------------------------------------------------------------------------


class TestDistributionLabelFull:
    def test_empty(self):
        assert distribution_label_full({}) == "n/a"

    def test_single(self):
        assert distribution_label_full({"devlog": 100}) == "n/a"

    def test_perfectly_balanced(self):
        counts = {"a": 100, "b": 100, "c": 100, "d": 100}
        assert distribution_label_full(counts) == "balanced"

    def test_nearly_balanced(self):
        counts = {"a": 100, "b": 98, "c": 102, "d": 100}
        assert distribution_label_full(counts) == "balanced"

    def test_skewed(self):
        # ideal = 100, max deviation = 10 → ratio = 0.10 → skewed
        counts = {"a": 110, "b": 90, "c": 100, "d": 100}
        assert distribution_label_full(counts) == "skewed"

    def test_unbalanced(self):
        # ideal = 100, max deviation = 50 → ratio = 0.50 → unbalanced
        counts = {"a": 150, "b": 50, "c": 100, "d": 100}
        assert distribution_label_full(counts) == "unbalanced"

    def test_zero_total(self):
        counts = {"a": 0, "b": 0}
        assert distribution_label_full(counts) == "n/a"

    def test_realistic_balanced(self):
        # 400 strokes across 6 categories, ~67 each
        counts = {
            "devlog": 67,
            "garden": 67,
            "note": 67,
            "thought": 67,
            "metrics": 66,
            "snippet": 66,
        }
        assert distribution_label_full(counts) == "balanced"


# ---------------------------------------------------------------------------
# VisitReport — header
# ---------------------------------------------------------------------------


class TestVisitReportHeader:
    def test_header_contains_visit_number(self):
        r = VisitReport(visit_number=147, timestamp="2026-10-16T02:00:00+08:00")
        assert "Visit 147" in r.render_header()

    def test_header_contains_timestamp(self):
        r = VisitReport(visit_number=1, timestamp="2026-10-16T02:00:00+08:00")
        assert "2026-10-16T02:00:00+08:00" in r.render_header()

    def test_header_healthy_emoji(self):
        r = VisitReport(visit_number=1, timestamp="t", severity="healthy")
        assert "🟢" in r.render_header()

    def test_header_recovered_emoji(self):
        r = VisitReport(visit_number=1, timestamp="t", severity="recovered")
        assert "🟡" in r.render_header()

    def test_header_degraded_emoji(self):
        r = VisitReport(visit_number=1, timestamp="t", severity="degraded")
        assert "🔴" in r.render_header()

    def test_invalid_severity_raises(self):
        with pytest.raises(ValueError, match="severity"):
            VisitReport(visit_number=1, timestamp="t", severity="critical")


# ---------------------------------------------------------------------------
# VisitReport — findings
# ---------------------------------------------------------------------------


class TestVisitReportFindings:
    def test_no_findings_shows_clean(self):
        r = VisitReport(visit_number=1, timestamp="t")
        out = r.render_findings()
        assert "No issues detected" in out

    def test_findings_rendered(self):
        r = VisitReport(
            visit_number=1,
            timestamp="t",
            findings=[
                Finding("writer dead", severity="critical"),
                Finding("backlog 9 files", severity="warning"),
            ],
        )
        out = r.render_findings()
        assert "writer dead" in out
        assert "backlog 9 files" in out
        assert "🔴" in out
        assert "⚠️" in out


# ---------------------------------------------------------------------------
# VisitReport — actions
# ---------------------------------------------------------------------------


class TestVisitReportActions:
    def test_no_actions_shows_none(self):
        r = VisitReport(visit_number=1, timestamp="t")
        out = r.render_actions()
        assert "No actions required" in out

    def test_actions_numbered(self):
        r = VisitReport(
            visit_number=1,
            timestamp="t",
            actions=[
                Action("commit backlog", success=True),
                Action("restart writer", success=True),
            ],
        )
        out = r.render_actions()
        assert "1. ✅ commit backlog" in out
        assert "2. ✅ restart writer" in out

    def test_failed_action_shown(self):
        r = VisitReport(
            visit_number=1,
            timestamp="t",
            actions=[Action("push failed", success=False)],
        )
        out = r.render_actions()
        assert "❌ push failed" in out


# ---------------------------------------------------------------------------
# VisitReport — metrics section
# ---------------------------------------------------------------------------


class TestVisitReportMetrics:
    def test_metrics_section_present(self):
        r = VisitReport(visit_number=1, timestamp="t")
        out = r.render_metrics()
        assert "### Metrics" in out

    def test_metrics_strokes_shown(self):
        r = VisitReport(
            visit_number=1,
            timestamp="t",
            metrics=Metrics(total_strokes=2910),
        )
        assert "2910" in r.render_metrics()


# ---------------------------------------------------------------------------
# VisitReport — full render
# ---------------------------------------------------------------------------


class TestVisitReportRender:
    def _make_report(self) -> VisitReport:
        return VisitReport(
            visit_number=147,
            timestamp="2026-10-16T02:00:00+08:00",
            severity="recovered",
            findings=[
                Finding("writer not running", severity="critical"),
                Finding("9 uncommitted files", severity="warning"),
            ],
            actions=[
                Action("committed backlog (9 files)", success=True),
                Action("restarted writer (pid 1467)", success=True),
                Action("restarted batch (pid 1468)", success=True),
            ],
            metrics=Metrics(
                total_strokes=2910,
                total_files=710,
                total_commits=1414,
                uncommitted_before=9,
                uncommitted_after=0,
                gap_seconds=2682,
                writer_running=True,
                batch_running=True,
            ),
            next_hint="check commit cadence adherence",
        )

    def test_full_render_contains_all_sections(self):
        r = self._make_report()
        md = r.render()
        assert "Visit 147" in md
        assert "Findings" in md
        assert "Actions" in md
        assert "Metrics" in md
        assert "Generated by" in md

    def test_full_render_contains_next_hint(self):
        r = self._make_report()
        assert "commit cadence adherence" in r.render()

    def test_full_render_contains_backlog_cleared(self):
        r = self._make_report()
        assert "cleared" in r.render()

    def test_no_next_hint_omits_line(self):
        r = VisitReport(visit_number=1, timestamp="t")
        assert "Next visit hint" not in r.render()


# ---------------------------------------------------------------------------
# VisitReport — properties
# ---------------------------------------------------------------------------


class TestVisitReportProperties:
    def test_is_healthy_true(self):
        r = VisitReport(visit_number=1, timestamp="t", severity="healthy")
        assert r.is_healthy is True

    def test_is_healthy_false(self):
        r = VisitReport(visit_number=1, timestamp="t", severity="degraded")
        assert r.is_healthy is False

    def test_needs_attention_true(self):
        r = VisitReport(visit_number=1, timestamp="t", severity="degraded")
        assert r.needs_attention is True

    def test_needs_attention_false(self):
        r = VisitReport(visit_number=1, timestamp="t", severity="recovered")
        assert r.needs_attention is False

    def test_failed_actions(self):
        r = VisitReport(
            visit_number=1,
            timestamp="t",
            actions=[
                Action("ok", success=True),
                Action("bad", success=False),
                Action("also ok", success=True),
            ],
        )
        assert len(r.failed_actions) == 1
        assert r.failed_actions[0].description == "bad"

    def test_critical_findings(self):
        r = VisitReport(
            visit_number=1,
            timestamp="t",
            findings=[
                Finding("info", severity="info"),
                Finding("crit", severity="critical"),
                Finding("warn", severity="warning"),
            ],
        )
        assert len(r.critical_findings) == 1
        assert r.critical_findings[0].description == "crit"

    def test_failed_actions_empty(self):
        r = VisitReport(
            visit_number=1,
            timestamp="t",
            actions=[Action("ok", success=True)],
        )
        assert r.failed_actions == []

    def test_critical_findings_empty(self):
        r = VisitReport(
            visit_number=1,
            timestamp="t",
            findings=[Finding("info", severity="info")],
        )
        assert r.critical_findings == []


# ---------------------------------------------------------------------------
# VisitReport — summary_dict
# ---------------------------------------------------------------------------


class TestVisitReportSummaryDict:
    def test_keys(self):
        r = VisitReport(visit_number=42, timestamp="t")
        d = r.summary_dict()
        expected_keys = {
            "visit", "severity", "findings", "critical",
            "actions", "failed_actions", "backlog_cleared",
            "writer_running", "batch_running", "gap_seconds",
        }
        assert set(d.keys()) == expected_keys

    def test_values(self):
        r = VisitReport(
            visit_number=147,
            timestamp="t",
            severity="recovered",
            findings=[Finding("c", severity="critical")],
            actions=[Action("fix", success=True)],
            metrics=Metrics(
                writer_running=True,
                batch_running=True,
                uncommitted_before=5,
                uncommitted_after=0,
                gap_seconds=120,
            ),
        )
        d = r.summary_dict()
        assert d["visit"] == 147
        assert d["severity"] == "recovered"
        assert d["findings"] == 1
        assert d["critical"] == 1
        assert d["actions"] == 1
        assert d["failed_actions"] == 0
        assert d["backlog_cleared"] is True
        assert d["writer_running"] is True
        assert d["batch_running"] is True
        assert d["gap_seconds"] == 120

    def test_healthy_defaults(self):
        r = VisitReport(visit_number=1, timestamp="t")
        d = r.summary_dict()
        assert d["severity"] == "healthy"
        assert d["findings"] == 0
        assert d["actions"] == 0
        assert d["backlog_cleared"] is False


# ---------------------------------------------------------------------------
# Integration: full render round-trip
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_healthy_visit(self):
        r = VisitReport(
            visit_number=100,
            timestamp="2026-10-15T10:00:00+08:00",
            severity="healthy",
            findings=[Finding("all systems nominal", severity="info")],
            metrics=Metrics(
                total_strokes=2500,
                total_files=680,
                total_commits=1350,
                writer_running=True,
                batch_running=True,
            ),
        )
        md = r.render()
        assert "🟢" in md
        assert "Healthy" in md
        assert "2500" in md

    def test_degraded_visit(self):
        r = VisitReport(
            visit_number=101,
            timestamp="2026-10-15T10:10:00+08:00",
            severity="degraded",
            findings=[Finding("push rejected", severity="critical")],
            actions=[
                Action("attempted rebase", success=True),
                Action("push retry", success=False, detail="conflict persists"),
            ],
            metrics=Metrics(
                total_strokes=2501,
                total_files=681,
                total_commits=1351,
                uncommitted_before=3,
                uncommitted_after=3,
                writer_running=True,
                batch_running=False,
            ),
            next_hint="resolve merge conflict on main",
        )
        md = r.render()
        assert "🔴" in md
        assert "Degraded" in md
        assert "conflict persists" in md
        assert "merge conflict" in md

    def test_recovered_visit_matches_current(self):
        """Modelled after the current visit: processes dead, recovered."""
        r = VisitReport(
            visit_number=147,
            timestamp="2026-10-16T02:00:00+08:00",
            severity="recovered",
            findings=[
                Finding("writer process not running", severity="critical"),
                Finding("batch process not running", severity="critical"),
                Finding("9 uncommitted files", severity="warning"),
            ],
            actions=[
                Action("committed 9 backlog files", success=True),
                Action("restarted writer (pid 1467)", success=True),
                Action("restarted batch (pid 1468)", success=True),
                Action("pushed to remote", success=True),
            ],
            metrics=Metrics(
                total_strokes=2910,
                total_files=710,
                total_commits=1414,
                uncommitted_before=9,
                uncommitted_after=0,
                gap_seconds=2682,
                writer_running=True,
                batch_running=True,
                extra={"python_files": 451, "logged_thoughts": 2910},
            ),
        )
        md = r.render()
        assert "Visit 147" in md
        assert "Recovered" in md
        assert "cleared" in md
        assert "44m 42s" in md
        assert "451" in md
