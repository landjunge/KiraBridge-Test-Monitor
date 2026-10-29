"""Bounded exact probe statistics and bounded rolling sample statistics."""
from collections import deque
import math
import statistics


MAX_PROBES = 10000
SAMPLE_WINDOW = 3600


def distribution(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return {"n": 0, "median": None, "p95": None, "max": None}
    return {"n": len(values), "median": statistics.median(values),
            "p95": values[math.ceil(0.95 * len(values)) - 1], "max": values[-1]}


class Summary:
    def __init__(self):
        self.probes = []  # CLI caps at MAX_PROBES; never silently evict baseline data
        self.samples = deque(maxlen=SAMPLE_WINDOW)
        self.sample_count = 0
        self.gaps = 0

    def add(self, record):
        if record["kind"] == "probe":
            if len(self.probes) >= MAX_PROBES:
                raise ValueError("probe limit exceeded")
            self.probes.append(record)
        elif record["kind"] == "sample":
            self.samples.append(record)
            self.sample_count += 1
        elif record.get("reason") == "sampling_gap":
            self.gaps += 1

    def report(self):
        count = len(self.probes)
        successes = [p for p in self.probes if p["status"] == "ok"]
        timeouts = sum(p["status"] == "timeout" for p in self.probes)
        errors = sum(p["status"] in ("error", "spawn_error") for p in self.probes)
        return {
            "probe_count": count, "success_count": len(successes),
            "timeout_count": timeouts, "timeout_rate": timeouts / count if count else None,
            "error_count": errors, "error_rate": errors / count if count else None,
            "cancelled_count": sum(p["status"] == "cancelled" for p in self.probes),
            "cleanup_failure_count": sum(not p["cleanup_ok"] for p in self.probes),
            "successful_latency_ms": distribution([p["duration_ns"] / 1e6 for p in successes]),
            "all_attempt_latency_ms": distribution([p["duration_ns"] / 1e6 for p in self.probes]),
            "sample_count": self.sample_count, "sample_window_count": len(self.samples),
            "sampling_gap_count": self.gaps,
            "sample_interval_seconds": distribution([s["elapsed_seconds"] for s in self.samples]),
            "wall_drift_abs_ms": distribution([abs(s["wall_drift_seconds"]) * 1000 for s in self.samples
                                                if s["wall_drift_seconds"] is not None]),
            "sampling_ms": distribution([s["sampling_ns"] / 1e6 for s in self.samples]),
            "self_cpu_percent_one_core": distribution([s["metrics"]["self_cpu_percent"] for s in self.samples]),
            "self_rss_bytes": distribution([s["metrics"]["self_rss_bytes"] for s in self.samples]),
        }
