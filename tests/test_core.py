from collections import namedtuple
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from kirabridge_monitor.clock import Clock
from kirabridge_monitor.metrics import Sampler, category, counter_rates, memory_pressure
from kirabridge_monitor.storage import BlackBox, CSVWriter, RotatingWriter, run_directory


class ClockTests(unittest.TestCase):
    def test_dual_clock_and_run_identity(self):
        clock = Clock()
        a, b = clock.stamp(), clock.stamp()
        self.assertLessEqual(a["monotonic_ns"], b["monotonic_ns"])
        self.assertEqual(a["run_id"], b["run_id"])
        self.assertNotEqual(a["run_id"], Clock().run_id)
        self.assertTrue(a["utc"].endswith("Z"))


class MetricTests(unittest.TestCase):
    def test_rates_warmup_reset_unavailable(self):
        self.assertEqual(counter_rates({"a": 20}, {"a": 10}, 2), {"a": 5})
        for old, seconds in [({}, 1), ({"a": 30}, 1), ({"a": 10}, 0)]:
            self.assertIsNone(counter_rates({"a": 20}, old, seconds)["a"])
        self.assertIsNone(counter_rates({"a": None}, {"a": 10}, 1)["a"])

    def test_fixed_categories(self):
        self.assertEqual(category("My secret project"), "other_busy")
        self.assertEqual(category("codex"), "codex")
        self.assertEqual(category("mdworker_shared"), "spotlight")
        self.assertEqual(category("backupd"), "backup")
        self.assertEqual(category("Terminal"), "terminal_display")

    def test_unsupported_pressure(self):
        with patch("kirabridge_monitor.metrics.platform.system", return_value="Linux"):
            self.assertEqual(memory_pressure(), (None, "unsupported"))

    def test_live_read_only_sample_and_no_content(self):
        sampler = Sampler(Clock())
        first = sampler.sample()
        second = sampler.sample()
        self.assertIsNone(first["metrics"]["cpu_percent"])
        self.assertGreaterEqual(second["elapsed_seconds"], 0)
        self.assertIsNotNone(first["metrics"]["ram_total_bytes"])
        text = json.dumps(second)
        for forbidden in ("cmdline", "environ", "cwd", "username", "pid", "prompt"):
            self.assertNotIn('"' + forbidden + '"', text)
        self.assertLess(second["processes_age_seconds"], 5)

    def test_unavailable_metrics_and_scan_throttling(self):
        import psutil
        sampler = Sampler(Clock())
        with patch.object(sampler.api, "disk_io_counters", side_effect=PermissionError), \
             patch.object(sampler.api, "process_iter", side_effect=psutil.AccessDenied) as scan:
            first = sampler.sample()
            sampler.sample()
        self.assertIsNone(first["metrics"]["disk_read_bytes"])
        self.assertEqual(first["status"]["disk"], "unavailable")
        self.assertIsNone(first["processes"])
        self.assertEqual(scan.call_count, 1)

    def test_repeated_monotonic_tick_produces_null_rates(self):
        sampler = Sampler(Clock())
        stamp = {"utc": "2026-10-30T00:00:00Z", "monotonic_ns": 1000000000}
        with patch.object(sampler.clock, "stamp", side_effect=lambda: dict(stamp)):
            sampler.sample()
            result = sampler.sample()
        self.assertEqual(result["elapsed_seconds"], 0)
        self.assertIsNone(result["metrics"]["self_cpu_percent"])
        for field, value in result["metrics"].items():
            if field.endswith("_per_second"):
                self.assertIsNone(value)

    def test_cpu_delta_and_wall_jump(self):
        cpu = namedtuple("CPU", "user system idle")
        sampler = Sampler(Clock())
        with patch.object(sampler.api, "cpu_times", side_effect=[cpu(1, 1, 8), cpu(3, 1, 16)]), \
             patch.object(sampler.clock, "stamp", side_effect=[
                 {"utc": "2026-10-30T00:00:00Z", "monotonic_ns": 1000000000},
                 {"utc": "2026-10-30T00:01:00Z", "monotonic_ns": 3000000000}]):
            sampler.sample()
            result = sampler.sample()
        self.assertAlmostEqual(result["metrics"]["cpu_percent"], 20)
        self.assertEqual(result["elapsed_seconds"], 2)
        self.assertEqual(result["wall_drift_seconds"], 58)


class StorageTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".tmp"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.directory = run_directory(self.temp.name)

    def test_private_and_exclusive(self):
        writer = RotatingWriter(self.directory / "samples.jsonl")
        self.addCleanup(writer.close)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(writer.path.stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            RotatingWriter(writer.path)
        self.assertNotEqual(run_directory(self.temp.name), self.directory)

    def test_strict_rotation_and_valid_json(self):
        writer = RotatingWriter(self.directory / "data.jsonl", max_bytes=256, backups=2)
        for i in range(100):
            writer.json({"index": i, "padding": "x" * 60})
        writer.close()
        files = list(self.directory.iterdir())
        self.assertEqual(len(files), 3)
        for file in files:
            self.assertLessEqual(file.stat().st_size, 256)
            for line in file.read_text().splitlines():
                json.loads(line)
        self.assertIn('"index":99', writer.path.read_text())

    def test_oversize_record_rejected_without_write(self):
        writer = RotatingWriter(self.directory / "data", max_bytes=256)
        self.addCleanup(writer.close)
        with self.assertRaises(ValueError):
            writer.write(b"x" * 257)
        self.assertEqual(writer.size, 0)

    def test_csv_rotation_repeats_header(self):
        writer = CSVWriter(self.directory / "data.csv", ["value"], max_bytes=256, backups=1)
        for _ in range(50):
            writer.record({"value": "x" * 30})
        writer.close()
        for file in self.directory.iterdir():
            self.assertTrue(file.read_bytes().startswith(b"value\r\n"))
            self.assertLessEqual(file.stat().st_size, 256)

    def test_symlink_not_followed(self):
        if os.name != "posix":
            self.skipTest("POSIX symlink permission semantics")
        target = self.directory / "target"
        target.write_text("safe")
        link = self.directory / "link"
        link.symlink_to(target)
        with self.assertRaises(FileExistsError):
            RotatingWriter(link)
        self.assertEqual(target.read_text(), "safe")

    def test_ring_prehistory_posthistory_and_merged_triggers(self):
        class MemoryWriter:
            def __init__(self):
                self.records = []
            def json(self, record):
                self.records.append(record)
        writer = MemoryWriter()
        box = BlackBox(writer, capacity=3, post_seconds=2)
        for n in range(5):
            box.observe({"kind": "sample", "monotonic_ns": n * 10**9})
        trigger = {"reason": "probe_timeout", "monotonic_ns": 5 * 10**9}
        box.observe(trigger)
        box.trigger(trigger)
        self.assertEqual([r["record"]["monotonic_ns"] for r in writer.records
                          if r["kind"] == "incident_record"], [3e9, 4e9, 5e9])
        trigger2 = {"reason": "probe_error", "monotonic_ns": 6 * 10**9}
        box.observe(trigger2)
        box.trigger(trigger2)
        box.observe({"monotonic_ns": 8 * 10**9})
        self.assertIsNone(box.active)
        self.assertEqual(box.incidents, 1)
        self.assertEqual(len(box.ring), 3)
        self.assertTrue(writer.records[-1]["post_window_complete"])

    def test_stop_marks_incomplete_and_invalid_reason(self):
        box = BlackBox(capacity=1)
        with self.assertRaises(ValueError):
            box.trigger({"monotonic_ns": 0, "reason": "secret content"})
        box.trigger({"monotonic_ns": 0, "reason": "manual_marker"})
        box.finish()
        self.assertIsNone(box.active)


if __name__ == "__main__":
    unittest.main()
