#!/usr/bin/env python3
"""
handoff_manager.py — Manage caretaker handoff artifact.

Ensures continuity between caretaker visits by maintaining a
structured handoff document that captures active investigations,
observations, and context that would otherwise be lost.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

HANDOFF_FILE = Path(__file__).parent.parent / "HANDOFF.md"
STALE_THRESHOLD_HOURS = 24


def load_handoff():
    """Load existing handoff document."""
    if not HANDOFF_FILE.exists():
        return None
    
    content = HANDOFF_FILE.read_text(encoding="utf-8")
    
    # Parse timestamp from first line
    timestamp = None
    for line in content.split("\n"):
        if line.startswith("# Handoff —"):
            try:
                ts_str = line.split("—")[1].strip()
                timestamp = datetime.fromisoformat(ts_str)
            except (IndexError, ValueError):
                pass
            break
    
    return {
        "content": content,
        "timestamp": timestamp,
        "stale": is_stale(timestamp) if timestamp else True
    }


def is_stale(timestamp):
    """Check if handoff is older than threshold."""
    if timestamp is None:
        return True
    age = datetime.now() - timestamp
    return age > timedelta(hours=STALE_THRESHOLD_HOURS)


def create_handoff(active_threads=None, observations=None, 
                   deprioritized=None, anomalies=None):
    """Create a new handoff document."""
    timestamp = datetime.now().isoformat(timespec="seconds")
    
    sections = []
    
    if active_threads:
        sections.append("## Active threads")
        for thread in active_threads:
            sections.append(f"- [ ] {thread}")
    
    if observations:
        sections.append("\n## Observations")
        for obs in observations:
            sections.append(f"- {obs}")
    
    if deprioritized:
        sections.append("\n## Deprioritized (with reasons)")
        for item in deprioritized:
            sections.append(f"- {item}")
    
    if anomalies:
        sections.append("\n## Anomalies explained")
        for anomaly in anomalies:
            sections.append(f"- {anomaly}")
    
    content = f"# Handoff — {timestamp}\n\n" + "\n".join(sections) + "\n"
    
    HANDOFF_FILE.write_text(content, encoding="utf-8")
    
    return {
        "status": "created",
        "timestamp": timestamp,
        "sections": len([s for s in sections if "## " in s])
    }


def read_handoff():
    """Read and analyze current handoff."""
    handoff = load_handoff()
    
    if handoff is None:
        return {
            "status": "missing",
            "message": "No handoff document exists. Run with --create to create one."
        }
    
    return {
        "status": "stale" if handoff["stale"] else "fresh",
        "timestamp": handoff["timestamp"].isoformat() if handoff["timestamp"] else None,
        "age_hours": (
            (datetime.now() - handoff["timestamp"]).total_seconds() / 3600
            if handoff["timestamp"] else None
        ),
        "content_preview": handoff["content"][:500] + "..." if len(handoff["content"]) > 500 else handoff["content"]
    }


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Manage caretaker handoff artifact")
    parser.add_argument("--read", action="store_true", help="Read current handoff")
    parser.add_argument("--create", action="store_true", help="Create new handoff")
    parser.add_argument("--stale-check", action="store_true", help="Check if handoff is stale")
    
    args = parser.parse_args()
    
    if args.read:
        result = read_handoff()
        print(json.dumps(result, indent=2))
    
    elif args.create:
        # Example creation - in practice, caretaker would provide these
        result = create_handoff(
            active_threads=["Investigating handoff protocol effectiveness"],
            observations=["Handoff document reduces context loss between visits"],
            deprioritized=["Lock scar analysis: stable, no action needed"],
            anomalies=["Gap in commits was scheduled maintenance"]
        )
        print(json.dumps(result, indent=2))
    
    elif args.stale_check:
        handoff = load_handoff()
        if handoff is None:
            print(json.dumps({"stale": True, "reason": "missing"}))
        else:
            print(json.dumps({
                "stale": handoff["stale"],
                "age_hours": (datetime.now() - handoff["timestamp"]).total_seconds() / 3600 if handoff["timestamp"] else None
            }))
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
