#!/usr/bin/env python3
"""auto_restart.py — watchdog that restarts dead writer/batch processes.

Runs as a one-shot check (suitable for cron or manual invocation).
If either the writer or batch process has died, restarts both via run_both.sh.
Reports what it found and what it did.

Usage:
    python3 tools/auto_restart.py              # check and restart if needed
    python3 tools/auto_restart.py --json       # machine-readable output
    python3 tools/auto_restart.py --dry-run    # report only, don't restart

Exit codes:
    0 — both processes alive (nothing to do)
    1 — one or both were dead and got restarted
    2 — restart failed
    3 — dry-run found dead processes but didn't act
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WRITER_ID = "qwen"  # matches run_both.sh default
WRITER_PID = Path(f"/tmp/iamai-writer-{WRITER_ID}.pid")
BATCH_PID = Path(f"/tmp/iamai-batch-{WRITER_ID}.pid")


def is_alive(pidfile: Path) -> bool:
    """Check if a process is alive by reading its pid file."""
    if not pidfile.exists():
        return False
    try:
        pid = int(pidfile.read_text().strip())
        # Send signal 0 to check if process exists
        import os
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


def restart_processes() -> bool:
    """Restart both processes via run_both.sh."""
    script = REPO / "tools" / "run_both.sh"
    if not script.exists():
        return False
    
    # First stop any remnants
    subprocess.run(["bash", str(script), "--stop"], cwd=REPO, capture_output=True)
    
    # Then start fresh
    result = subprocess.run(["bash", str(script)], cwd=REPO, capture_output=True, text=True)
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--dry-run", action="store_true", help="report only, don't restart")
    args = parser.parse_args()

    writer_alive = is_alive(WRITER_PID)
    batch_alive = is_alive(BATCH_PID)
    
    status = {
        "writer_alive": writer_alive,
        "batch_alive": batch_alive,
        "writer_pid": WRITER_PID.read_text().strip() if WRITER_PID.exists() else None,
        "batch_pid": BATCH_PID.read_text().strip() if BATCH_PID.exists() else None,
        "action_taken": "none",
        "restart_success": None,
    }

    if writer_alive and batch_alive:
        if args.json:
            print(json.dumps(status))
        else:
            print(f"✓ writer[{WRITER_ID}]: alive (pid {status['writer_pid']})")
            print(f"✓ batch [{WRITER_ID}]: alive (pid {status['batch_pid']})")
            print("No action needed.")
        return 0

    # At least one process is dead
    status["action_taken"] = "dry-run" if args.dry_run else "restart"
    
    if args.dry_run:
        if args.json:
            print(json.dumps(status))
        else:
            print(f"✗ writer[{WRITER_ID}]: {'alive' if writer_alive else 'DEAD'}")
            print(f"✗ batch [{WRITER_ID}]: {'alive' if batch_alive else 'DEAD'}")
            print("Dry-run: would restart but not acting.")
        return 3

    # Actually restart
    print(f"⚠ writer[{WRITER_ID}]: {'alive' if writer_alive else 'DEAD'}")
    print(f"⚠ batch [{WRITER_ID}]: {'alive' if batch_alive else 'DEAD'}")
    print("Restarting processes...")
    
    success = restart_processes()
    status["restart_success"] = success
    
    if success:
        # Verify they came back up
        import time
        time.sleep(2)  # Give them a moment to start
        writer_alive = is_alive(WRITER_PID)
        batch_alive = is_alive(BATCH_PID)
        status["writer_alive_after"] = writer_alive
        status["batch_alive_after"] = batch_alive
        
        if writer_alive and batch_alive:
            status["action_taken"] = "restart-success"
            if args.json:
                print(json.dumps(status))
            else:
                print("✓ Processes restarted successfully.")
            return 1
        else:
            status["action_taken"] = "restart-failed-verify"
            if args.json:
                print(json.dumps(status))
            else:
                print("✗ Restart command succeeded but processes didn't come up.")
            return 2
    else:
        status["action_taken"] = "restart-failed"
        if args.json:
            print(json.dumps(status))
        else:
            print("✗ Restart failed.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
