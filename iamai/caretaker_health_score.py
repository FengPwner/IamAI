#!/usr/bin/env python3
"""caretaker_health_score — composite health metric for the IamAI system.

Aggregates multiple signals into a single 0-100 health score:
- Writer cadence (is it producing strokes on time?)
- Commit freshness (are changes being committed regularly?)
- Stroke diversity (is content varied or repetitive?)
- Backlog pressure (how many uncommitted files?)
- Process uptime (are writer and batch processes running?)

Usage:
    from iamai.caretaker_health_score import HealthScore
    
    scorer = HealthScore()
    result = scorer.calculate(repo_path)
    print(f"Health: {result.score}/100 ({result.verdict})")

CLI:
    python3 tools/caretaker_health_score.py
    python3 tools/caretaker_health_score.py --json
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class HealthResult:
    """Composite health assessment."""
    score: int  # 0-100
    verdict: str  # "healthy", "degraded", "critical"
    components: dict[str, int]  # individual component scores
    details: dict[str, Any]  # raw metrics


class HealthScore:
    """Calculate composite health score for IamAI system."""
    
    # Weights for each component (must sum to 1.0)
    WEIGHTS = {
        "cadence": 0.25,
        "freshness": 0.20,
        "diversity": 0.20,
        "backlog": 0.20,
        "processes": 0.15,
    }
    
    def __init__(self, cadence_target: int = 900, freshness_target: int = 3600):
        """Initialize with target thresholds.
        
        Args:
            cadence_target: Expected seconds between strokes (default 15min)
            freshness_target: Max acceptable seconds since last commit (default 1hr)
        """
        self.cadence_target = cadence_target
        self.freshness_target = freshness_target
    
    def calculate(self, repo: Path) -> HealthResult:
        """Calculate composite health score.
        
        Args:
            repo: Path to repository root
            
        Returns:
            HealthResult with score, verdict, and component breakdown
        """
        components = {}
        details = {}
        
        # 1. Cadence score
        cadence_score, cadence_details = self._score_cadence(repo)
        components["cadence"] = cadence_score
        details["cadence"] = cadence_details
        
        # 2. Commit freshness score
        freshness_score, freshness_details = self._score_freshness(repo)
        components["freshness"] = freshness_score
        details["freshness"] = freshness_details
        
        # 3. Stroke diversity score
        diversity_score, diversity_details = self._score_diversity(repo)
        components["diversity"] = diversity_score
        details["diversity"] = diversity_details
        
        # 4. Backlog pressure score
        backlog_score, backlog_details = self._score_backlog(repo)
        components["backlog"] = backlog_score
        details["backlog"] = backlog_details
        
        # 5. Process uptime score
        process_score, process_details = self._score_processes(repo)
        components["processes"] = process_score
        details["processes"] = process_details
        
        # Calculate weighted composite
        total = sum(
            components[k] * self.WEIGHTS[k]
            for k in self.WEIGHTS
        )
        score = int(round(total))
        
        # Determine verdict
        if score >= 80:
            verdict = "healthy"
        elif score >= 60:
            verdict = "degraded"
        else:
            verdict = "critical"
        
        return HealthResult(
            score=score,
            verdict=verdict,
            components=components,
            details=details,
        )
    
    def _score_cadence(self, repo: Path) -> tuple[int, dict]:
        """Score writer cadence (stroke production rate)."""
        strokes_path = repo / "data" / "strokes.jsonl"
        if not strokes_path.exists():
            return 0, {"error": "no strokes file", "avg_gap": None}
        
        try:
            lines = strokes_path.read_text().strip().splitlines()
            if len(lines) < 2:
                return 50, {"avg_gap": None, "note": "insufficient data"}
            
            # Parse last 10 strokes
            recent = []
            for line in lines[-10:]:
                try:
                    recent.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            
            if len(recent) < 2:
                return 50, {"avg_gap": None, "note": "insufficient valid strokes"}
            
            # Calculate average gap
            timestamps = [s.get("ts", 0) for s in recent if "ts" in s]
            if len(timestamps) < 2:
                return 50, {"avg_gap": None, "note": "no timestamps"}
            
            gaps = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
            avg_gap = sum(gaps) / len(gaps)
            
            # Score: 100 if at target, degrades as gap increases
            if avg_gap <= self.cadence_target:
                score = 100
            elif avg_gap <= self.cadence_target * 2:
                # Linear degradation from 100 to 50
                score = int(100 - 50 * (avg_gap - self.cadence_target) / self.cadence_target)
            else:
                # Below 50 for gaps > 2x target
                score = max(0, int(50 - (avg_gap - self.cadence_target * 2) / 60))
            
            return score, {"avg_gap": int(avg_gap), "target": self.cadence_target}
            
        except Exception as e:
            return 0, {"error": str(e)}
    
    def _score_freshness(self, repo: Path) -> tuple[int, dict]:
        """Score commit freshness (time since last commit)."""
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ct"],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return 0, {"error": "git log failed"}
            
            last_commit_ts = int(result.stdout.strip())
            now = time.time()
            age_seconds = now - last_commit_ts
            
            # Score: 100 if fresh, degrades as age increases
            if age_seconds <= self.freshness_target:
                score = 100
            elif age_seconds <= self.freshness_target * 2:
                score = int(100 - 50 * (age_seconds - self.freshness_target) / self.freshness_target)
            else:
                score = max(0, int(50 - (age_seconds - self.freshness_target * 2) / 600))
            
            return score, {"age_seconds": int(age_seconds), "target": self.freshness_target}
            
        except Exception as e:
            return 0, {"error": str(e)}
    
    def _score_diversity(self, repo: Path) -> tuple[int, dict]:
        """Score stroke content diversity."""
        strokes_path = repo / "data" / "strokes.jsonl"
        if not strokes_path.exists():
            return 50, {"note": "no strokes file"}
        
        try:
            lines = strokes_path.read_text().strip().splitlines()
            if len(lines) < 10:
                return 50, {"note": "insufficient data"}
            
            # Check last 20 strokes for category diversity
            recent = []
            for line in lines[-20:]:
                try:
                    recent.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            
            if not recent:
                return 50, {"note": "no valid strokes"}
            
            categories = [s.get("category", "unknown") for s in recent]
            unique_cats = len(set(categories))
            
            # Score based on number of unique categories
            # 6+ categories = 100, fewer = lower score
            score = min(100, unique_cats * 16)
            
            return score, {"unique_categories": unique_cats, "sample_size": len(recent)}
            
        except Exception as e:
            return 50, {"error": str(e)}
    
    def _score_backlog(self, repo: Path) -> tuple[int, dict]:
        """Score based on uncommitted file count."""
        try:
            # Use -uall to show all untracked files individually
            result = subprocess.run(
                ["git", "status", "--porcelain", "-uall"],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return 0, {"error": "git status failed"}
            
            # Count all non-empty lines (each represents a pending file)
            lines = [line for line in result.stdout.splitlines() if line.strip()]
            pending = len(lines)
            
            # Score: 100 if clean, degrades with more pending files
            if pending == 0:
                score = 100
            elif pending <= 5:
                score = 100 - pending * 10  # 90, 80, 70, 60, 50
            elif pending <= 15:
                score = max(20, 50 - (pending - 5) * 3)
            else:
                score = max(0, 20 - (pending - 15) * 2)
            
            return score, {"pending_files": pending}
            
        except Exception as e:
            return 50, {"error": str(e)}
    
    def _score_processes(self, repo: Path) -> tuple[int, dict]:
        """Score based on writer and batch process status."""
        try:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            
            writer_running = "writer_loop.py" in result.stdout
            batch_running = "commit_batch.py" in result.stdout
            
            if writer_running and batch_running:
                score = 100
                details = {"writer": True, "batch": True}
            elif writer_running or batch_running:
                score = 50
                details = {"writer": writer_running, "batch": batch_running}
            else:
                score = 0
                details = {"writer": False, "batch": False}
            
            return score, details
            
        except Exception as e:
            return 50, {"error": str(e)}


def main() -> int:
    """CLI entry point."""
    import argparse
    
    ap = argparse.ArgumentParser(description="Calculate IamAI system health score")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent,
                   help="Repository root path")
    args = ap.parse_args()
    
    scorer = HealthScore()
    result = scorer.calculate(args.repo)
    
    if args.json:
        print(json.dumps({
            "score": result.score,
            "verdict": result.verdict,
            "components": result.components,
            "details": result.details,
        }, indent=2))
    else:
        print(f"Health Score: {result.score}/100 ({result.verdict})")
        print("\nComponents:")
        for comp, score in sorted(result.components.items()):
            print(f"  {comp:12s} {score:3d}")
        
        if result.verdict != "healthy":
            print(f"\n⚠️  System is {result.verdict}")
            return 1
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
