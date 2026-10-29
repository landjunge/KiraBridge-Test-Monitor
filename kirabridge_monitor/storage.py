"""Bounded local persistence in a unique private run directory."""
from collections import deque
import csv
import io
import json
import os
from pathlib import Path
import uuid


def run_directory(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = root / ("run-" + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)  # exclusive, never reuse another run
    return directory


class RotatingWriter:
    """Strict byte cap per file; one writer owns each stream in its run."""
    def __init__(self, path, max_bytes=1024 * 1024, backups=3, header=b""):
        if max_bytes < 256 or backups < 0 or len(header) >= max_bytes:
            raise ValueError("invalid rotation limits")
        self.path = Path(path)
        self.max_bytes, self.backups, self.header = max_bytes, backups, header
        self.handle = None
        self.size = 0
        self._open()

    def _open(self):
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path, flags, 0o600)
        self.handle = os.fdopen(fd, "wb", buffering=0)
        self.size = 0
        if self.header:
            self.handle.write(self.header)
            self.size = len(self.header)

    def _rotate(self):
        self.handle.close()
        if self.backups:
            oldest = Path(str(self.path) + "." + str(self.backups))
            oldest.unlink(missing_ok=True)
            for index in range(self.backups - 1, 0, -1):
                src = Path(str(self.path) + "." + str(index))
                if src.exists():
                    src.replace(str(self.path) + "." + str(index + 1))
            self.path.replace(str(self.path) + ".1")
        else:
            self.path.unlink()
        self._open()

    def write(self, data):
        if len(data) + len(self.header) > self.max_bytes:
            raise ValueError("record exceeds file limit")
        if self.size + len(data) > self.max_bytes:
            self._rotate()
        self.handle.write(data)
        self.size += len(data)

    def json(self, record):
        self.write((json.dumps(record, separators=(",", ":"), allow_nan=False)
                    + "\n").encode("utf-8"))

    def close(self):
        if self.handle is not None:
            self.handle.close()


class CSVWriter(RotatingWriter):
    def __init__(self, path, fields, **kwargs):
        self.fields = fields
        super().__init__(path, header=self._row(fields), **kwargs)

    @staticmethod
    def _row(values):
        output = io.StringIO(newline="")
        csv.writer(output).writerow(values)
        return output.getvalue().encode("utf-8")

    def record(self, record):
        self.write(self._row([record.get(key) for key in self.fields]))


class BlackBox:
    """One merged incident at a time; bounded prehistory and posthistory."""
    def __init__(self, writer=None, capacity=120, post_seconds=10):
        if capacity < 1 or post_seconds < 0:
            raise ValueError("invalid blackbox limits")
        self.ring = deque(maxlen=capacity)
        self.writer = writer
        self.post_ns = int(post_seconds * 1e9)
        self.active = None
        self.incidents = 0

    def _write(self, record):
        if self.writer:
            self.writer.json(record)

    def observe(self, record):
        now = record["monotonic_ns"]
        if self.active and now > self.active["deadline_ns"]:
            self.finish(complete=True)
        self.ring.append(record)
        if self.active:
            self._write({"kind": "incident_record", "incident_id": self.active["id"],
                         "record": record})
            if now >= self.active["deadline_ns"]:
                self.finish(complete=True)

    def trigger(self, record):
        """Trigger must already have been observed. Accept fixed reasons only."""
        reason = record.get("reason")
        if reason not in ("probe_timeout", "probe_error", "manual_marker", "sampling_gap"):
            raise ValueError("unsupported incident reason")
        now = record["monotonic_ns"]
        if self.active:
            self.active["deadline_ns"] = min(self.active["max_deadline_ns"], now + self.post_ns)
            self._write({"kind": "incident_trigger", "incident_id": self.active["id"],
                         "reason": reason, "monotonic_ns": now})
            return
        self.incidents += 1
        self.active = {"id": str(uuid.uuid4()), "deadline_ns": now + self.post_ns,
                       "max_deadline_ns": now + 2 * self.post_ns}
        self._write({"kind": "incident_start", "incident_id": self.active["id"],
                     "reason": reason, "monotonic_ns": now})
        for item in self.ring:
            self._write({"kind": "incident_record", "incident_id": self.active["id"],
                         "record": item})
        if not self.post_ns:
            self.finish(complete=True)

    def finish(self, complete=False):
        if self.active:
            self._write({"kind": "incident_end", "incident_id": self.active["id"],
                         "post_window_complete": complete})
            self.active = None
