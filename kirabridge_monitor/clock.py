"""Dual clock: wall time for correlation, monotonic time for durations."""
from datetime import datetime, timezone
import time
import uuid


class Clock:
    def __init__(self):
        self.run_id = str(uuid.uuid4())

    def stamp(self):
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "monotonic_ns": time.monotonic_ns(),
        }
