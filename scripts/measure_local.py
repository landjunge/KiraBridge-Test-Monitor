#!/usr/bin/env python3
"""Sequential reproducible research run; no load generation or session control.

Run from the repository root: .venv/bin/python scripts/measure_local.py
Raw data and the complete numerical report stay under ignored ./runs/.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import sys

import psutil

from kirabridge_monitor.runner import overhead, run_session
from kirabridge_monitor.storage import RotatingWriter, run_directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="runs")
    parser.add_argument("--idle-seconds", type=float, default=60)
    parser.add_argument("--repetitions", type=int, default=100)
    parser.add_argument("--rounds", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.idle_seconds <= 3600 or not 1 <= args.repetitions <= 10000 or not 1 <= args.rounds <= 10:
        parser.error("parameters out of bounds")
    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    directory = run_directory(args.output)
    print("Six baseline trials (default), then two idle runs; all sequential.", file=sys.stderr)
    trials = overhead(repetitions=args.repetitions, rounds=args.rounds, output=args.output,
                      interval=1, timeout=2, post=10)
    idle = []
    if not trials["interrupted"]:
        for mode in ("memory", "logging"):
            print("Idle monitor: " + mode, file=sys.stderr)
            result = run_session(mode=mode, output=args.output, interval=1, duration=args.idle_seconds)
            idle.append(result)
            if result["interrupted"]:
                break
    report = {
        "task_id": "monitor-codex-development-brief-20261029", "schema_version": 1,
        "utc": datetime.now(timezone.utc).isoformat(), "code_commit": git_head,
        "dirty_worktree": dirty, "os": platform.system(), "os_release": platform.release(),
        "architecture": platform.machine(), "python": platform.python_version(),
        "psutil": psutil.__version__, "logical_cpus": psutil.cpu_count(),
        "physical_cpus": psutil.cpu_count(logical=False),
        "ram_total_bytes": psutil.virtual_memory().total,
        "method": "1 Hz; sequential; seed 20261029; no process/session manipulation; existing workload uncontrolled",
        "overhead": trials, "idle": idle,
    }
    # Strip output-root paths; only opaque local run names belong in the report.
    for result in trials["trials"] + idle:
        if result["directory"]:
            result["directory"] = Path(result["directory"]).name
    writer = RotatingWriter(directory / "report.json", max_bytes=1048576, backups=0)
    try:
        writer.json(report)
    finally:
        writer.close()
    print(json.dumps({"report": str(directory / "report.json"), "code_commit": git_head}, indent=2))
    return 130 if trials["interrupted"] or any(r["interrupted"] for r in idle) else (
        1 if any(r["timeout_count"] or r["error_count"] or r["worker_failed"]
                 or not r["worker_stopped"] or r["cleanup_failure_count"]
                 for r in trials["trials"] + idle) else 0)


if __name__ == "__main__":
    raise SystemExit(main())
