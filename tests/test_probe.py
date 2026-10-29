import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from kirabridge_monitor.cli import main, parser
from kirabridge_monitor.clock import Clock
from kirabridge_monitor.probe import SCENARIOS, command, probe_once, wait_owned
from kirabridge_monitor.report import Summary, distribution
from kirabridge_monitor.runner import run_session


@unittest.skipUnless(os.name == "posix", "POSIX synthetic shell probes")
class ProbeTests(unittest.TestCase):
    def test_builtin_scenarios_no_content(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                record = probe_once(scenario, 3, Clock())
                self.assertEqual(record["status"], "ok")
                self.assertTrue(record["cleanup_ok"])
                self.assertGreater(record["duration_ns"], 0)
                self.assertGreaterEqual(record["monotonic_ns"], record["started_monotonic_ns"])
                self.assertNotIn("stdout", record)
                self.assertNotIn("stderr", record)
                self.assertNotIn("argv", record)
        with self.assertRaises(ValueError):
            command("echo secrets")

    def test_nonzero_and_spawn_error(self):
        self.assertEqual(wait_owned([sys.executable, "-I", "-c", "raise SystemExit(7)"], 3)["exit_code"], 7)
        self.assertEqual(wait_owned(["/not-a-real-executable"], 1)["status"], "spawn_error")

    def test_timeout_reaps_only_owned_child(self):
        other = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(20)"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            created = []
            real_popen = subprocess.Popen
            def own(*args, **kwargs):
                child = real_popen(*args, **kwargs)
                created.append(child)
                return child
            with patch("kirabridge_monitor.probe.subprocess.Popen", side_effect=own):
                result = wait_owned([sys.executable, "-I", "-c", "import time; time.sleep(20)"], 0.03)
            self.assertEqual(result["status"], "timeout")
            self.assertTrue(result["cleanup_ok"])
            self.assertIsNotNone(created[0].returncode)
            self.assertIsNone(other.poll())  # unrelated child remains alive
        finally:
            other.kill()
            other.wait(timeout=3)

    def test_cancellation_and_keyboard_interrupt_cleanup(self):
        cancelled = threading.Event()
        cancelled.set()
        result = wait_owned([sys.executable, "-I", "-c", "import time; time.sleep(10)"], 3, cancelled)
        self.assertEqual(result["status"], "cancelled")
        self.assertTrue(result["cleanup_ok"])

    def test_no_startup_environment_passed(self):
        with patch.dict(os.environ, {"ENV": "/private/startup", "BASH_ENV": "/private/startup"}):
            real_popen = subprocess.Popen
            with patch("kirabridge_monitor.probe.subprocess.Popen", wraps=real_popen) as spawn:
                self.assertEqual(probe_once("noop", 3, Clock())["status"], "ok")
            self.assertEqual(spawn.call_args.kwargs["env"], {"PATH": os.defpath})
            self.assertEqual(spawn.call_args.kwargs["stdout"], subprocess.DEVNULL)


class ReportTests(unittest.TestCase):
    def test_nearest_rank_p95_and_median(self):
        stats = distribution(list(range(1, 101)))
        self.assertEqual(stats["median"], 50.5)
        self.assertEqual(stats["p95"], 95)
        self.assertIsNone(distribution([None])["median"])

    def test_timeouts_excluded_from_success_distribution(self):
        summary = Summary()
        for status, duration in [("ok", 1), ("ok", 3), ("timeout", 100), ("error", 7)]:
            summary.add({"kind": "probe", "status": status, "duration_ns": duration * 10**6,
                         "cleanup_ok": True})
        report = summary.report()
        self.assertEqual(report["successful_latency_ms"]["median"], 2)
        self.assertEqual(report["timeout_rate"], 0.25)
        self.assertEqual(report["error_rate"], 0.25)


@unittest.skipUnless(os.name == "posix", "POSIX local integration")
class SessionTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".tmp"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.output = str(Path(self.temp.name) / "output")

    def test_100_probe_baseline_and_private_artifacts(self):
        result = run_session(output=self.output, repetitions=100, interval=0.1, post=0)
        self.assertEqual(result["probe_count"], 100)
        self.assertEqual(result["success_count"], 100)
        self.assertTrue(result["worker_stopped"])
        directory = Path(result["directory"])
        lines = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
        self.assertEqual(len(lines), 100)
        self.assertEqual(len((directory / "probes.csv").read_text().splitlines()), 101)
        self.assertEqual(json.loads((directory / "summary.json").read_text())["probe_count"], 100)
        self.assertEqual(lines[0]["run_id"], result["run_id"])

    def test_memory_and_off_create_no_files(self):
        for mode in ("off", "memory"):
            result = run_session(mode=mode, output=self.output, repetitions=2, interval=0.1)
            self.assertEqual(result["success_count"], 2)
            self.assertEqual(result["sample_count"] == 0, mode == "off")
            self.assertIsNone(result["directory"])
        self.assertFalse(Path(self.output).exists())

    def test_monitor_stop_marks_incomplete_incident(self):
        result = run_session(output=self.output, duration=0.1, interval=0.1, marker=True, post=10)
        self.assertTrue(result["incomplete_post_window"])
        lines = [json.loads(line) for line in (Path(result["directory"]) / "incidents.jsonl").read_text().splitlines()]
        self.assertEqual(lines[-1]["kind"], "incident_end")
        self.assertFalse(lines[-1]["post_window_complete"])

    def test_timeout_blackbox_post_capture(self):
        def timeout_probe(scenario, timeout, clock, stop):
            return {**clock.stamp(), "kind": "probe", "status": "timeout", "duration_ns": 1000000,
                    "cleanup_ok": True}
        with patch("kirabridge_monitor.runner.probe_once", side_effect=timeout_probe):
            result = run_session(output=self.output, repetitions=1, interval=0.01, post=0.05)
        self.assertEqual(result["timeout_count"], 1)
        self.assertEqual(result["incidents"], 1)
        self.assertFalse(result["incomplete_post_window"])
        lines = [json.loads(line) for line in (Path(result["directory"]) / "incidents.jsonl").read_text().splitlines()]
        self.assertTrue(lines[-1]["post_window_complete"])
        self.assertTrue(any(r.get("record", {}).get("kind") == "sample" for r in lines))

    def test_keyboard_interrupt_closes_writers_and_marks_summary(self):
        with patch("kirabridge_monitor.runner.Sampler.sample", side_effect=KeyboardInterrupt):
            result = run_session(output=self.output, duration=1)
        self.assertTrue(result["interrupted"])
        self.assertTrue((Path(result["directory"]) / "summary.json").exists())

    def test_worker_failure_visible(self):
        with patch("kirabridge_monitor.runner.probe_once", side_effect=RuntimeError("private")):
            result = run_session(mode="off", repetitions=2)
        self.assertTrue(result["worker_failed"])
        self.assertNotIn("private", json.dumps(result))


class CLITests(unittest.TestCase):
    def test_reject_invalid_numbers(self):
        import contextlib
        import io
        for args in (["baseline", "--repetitions", "0"], ["monitor", "--interval", "nan"],
                     ["monitor", "--interval", "inf"], ["monitor", "--ring", "4000"],
                     ["baseline", "--codex-instances", "3"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser().parse_args(args)

    def test_cli_result_exit_status_and_json(self):
        import contextlib
        import io
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["baseline", "--mode", "off", "--repetitions", "2"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["probe_count"], 2)


if __name__ == "__main__":
    unittest.main()
