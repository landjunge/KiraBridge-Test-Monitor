"""Small explicit CLI; no background service or arbitrary command execution."""
import argparse
import json
import math
import sys

from . import __version__
from .probe import SCENARIOS
from .runner import overhead, run_session


def bounded_number(low, high, integer=False):
    def parse(value):
        try:
            result = int(value) if integer else float(value)
        except ValueError:
            raise argparse.ArgumentTypeError("expected a number")
        if not math.isfinite(result) or not low <= result <= high:
            raise argparse.ArgumentTypeError("expected %s..%s" % (low, high))
        return result
    return parse


def parser():
    root = argparse.ArgumentParser(description="Private resource monitor and synthetic local probes")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="operation", required=True)
    for name in ("monitor", "baseline", "overhead"):
        sub = commands.add_parser(name)
        sub.add_argument("--output", default="runs", help="local output root (default: runs)")
        sub.add_argument("--interval", type=bounded_number(0.1, 60), default=1.0)
        sub.add_argument("--duration", type=bounded_number(0.1, 86400), default=60.0,
                         help="monitor duration in seconds; baseline runs until probes and post-window finish")
        sub.add_argument("--ring", type=bounded_number(1, 3600, True), default=120,
                         help="maximum prehistory records, samples plus probe events")
        sub.add_argument("--post", type=bounded_number(0, 60), default=10.0)
        sub.add_argument("--max-bytes", type=bounded_number(16384, 16777216, True), default=1048576)
        sub.add_argument("--backups", type=bounded_number(0, 10, True), default=3)
        sub.add_argument("--windows", type=bounded_number(1, 20, True), default=1,
                         help="declared experiment factor; never opens windows")
        sub.add_argument("--codex-instances", type=bounded_number(0, 2, True), default=None,
                         help="declared factor, not detection or process control")
        sub.add_argument("--marker", action="store_true", help="fixed manual blackbox marker at start")
        if name == "monitor":
            sub.add_argument("--no-logging", action="store_true", help="memory only; no files created")
        else:
            sub.add_argument("--repetitions", type=bounded_number(1, 10000, True), default=100)
            sub.add_argument("--scenario", choices=SCENARIOS, default="noop")
            sub.add_argument("--timeout", type=bounded_number(0.001, 60), default=2.0)
            if name == "baseline":
                sub.add_argument("--mode", choices=("off", "memory", "logging"), default="logging")
            else:
                sub.add_argument("--rounds", type=bounded_number(1, 10, True), default=2)
                sub.add_argument("--seed", type=int, default=20261029)
    return root


def main(argv=None):
    args = vars(parser().parse_args(argv))
    operation = args.pop("operation")
    if operation == "monitor":
        args["mode"] = "memory" if args.pop("no_logging") else "logging"
    try:
        result = overhead(**args) if operation == "overhead" else run_session(**args)
    except (OSError, ValueError, NotImplementedError) as error:
        # No exception text: it could contain a private local path.
        print(json.dumps({"error": type(error).__name__, "errno": getattr(error, "errno", None)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, allow_nan=False))
    if result["interrupted"]:
        return 130
    trials = result.get("trials", [result])
    return 1 if any(t["worker_failed"] or not t["worker_stopped"] or t["error_count"]
                    or t["timeout_count"] or t["cleanup_failure_count"] for t in trials) else 0
