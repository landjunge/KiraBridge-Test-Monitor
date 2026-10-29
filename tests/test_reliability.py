"""Failure paths and retention boundaries that matter for unattended research."""
from collections import namedtuple
from contextlib import nullcontext
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from kirabridge_monitor.clock import Clock
from kirabridge_monitor.metrics import Sampler, memory_pressure
from kirabridge_monitor.probe import wait_owned
from kirabridge_monitor.report import SAMPLE_WINDOW, Summary
from kirabridge_monitor.runner import run_session
from kirabridge_monitor.storage import BlackBox


class ResourceReliabilityTests(unittest.TestCase):
    def test_process_cpu_pruned_identity_and_private_name(self):
        def proc(pid, born, name, cpu):
            return SimpleNamespace(pid=pid, oneshot=nullcontext, name=lambda: name,
                                   create_time=lambda: born,
                                   cpu_times=lambda: SimpleNamespace(user=cpu, system=0),
                                   memory_info=lambda: SimpleNamespace(rss=1000))
        sampler = Sampler(Clock())
        first = [proc(10, 1, "codex", 1), proc(20, 1, "SECRET_CANARY", 1)]
        second = [proc(10, 1, "codex", 2), proc(20, 1, "SECRET_CANARY", 2)]
        third = [proc(10, 2, "codex", 50)]  # reused PID must not inherit old CPU
        with patch.object(sampler.api, "process_iter", side_effect=[first, second, third]):
            sampler._processes(0)
            self.assertIsNone(sampler.process_data["groups"]["codex"]["cpu_percent"])
            sampler._processes(5)
            self.assertEqual(sampler.process_data["groups"]["codex"]["cpu_percent"], 20)
            self.assertEqual(sampler.process_data["groups"]["other_busy"]["count"], 1)
            self.assertNotIn("SECRET_CANARY", json.dumps(sampler.process_data))
            sampler._processes(10)
        self.assertEqual(len(sampler.process_cpu), 1)
        self.assertIsNone(sampler.process_data["groups"]["codex"]["cpu_percent"])

    def test_cpu_counter_reset_is_null(self):
        cpu = namedtuple("CPU", "user system idle")
        sampler = Sampler(Clock())
        with patch.object(sampler.api, "cpu_times", side_effect=[cpu(5, 5, 10), cpu(1, 1, 1)]):
            sampler.sample()
            result = sampler.sample()
        self.assertIsNone(result["metrics"]["cpu_percent"])

    def test_kernel_pressure_failure_is_explicit(self):
        call = SimpleNamespace(sysctlbyname=lambda *args: -1)
        # Use a callable object so ctypes signature assignments are supported.
        class FailingCall:
            def __call__(self, *args):
                return -1
        call.sysctlbyname = FailingCall()
        with patch("kirabridge_monitor.metrics.platform.system", return_value="Darwin"), \
             patch("kirabridge_monitor.metrics.ctypes.CDLL", return_value=call):
            self.assertEqual(memory_pressure(), (None, "unavailable"))

    def test_sample_summary_window_is_bounded(self):
        summary = Summary()
        for _ in range(SAMPLE_WINDOW + 5):
            summary.add({"kind": "sample", "sampling_ns": 1, "elapsed_seconds": 1,
                         "wall_drift_seconds": 0,
                         "metrics": {"self_cpu_percent": 0, "self_rss_bytes": 1000}})
        result = summary.report()
        self.assertEqual(result["sample_count"], SAMPLE_WINDOW + 5)
        self.assertEqual(result["sample_window_count"], SAMPLE_WINDOW)

    def test_blackbox_overlap_cannot_extend_forever(self):
        box = BlackBox(capacity=3, post_seconds=2)
        for second in range(4):
            record = {"monotonic_ns": second * 10**9, "reason": "probe_error"}
            box.observe(record)
            box.trigger(record)
        self.assertEqual(box.active["deadline_ns"], 4 * 10**9)
        box.observe({"monotonic_ns": 4 * 10**9})
        self.assertIsNone(box.active)
        self.assertEqual(box.incidents, 1)

    def test_api_rejects_unbounded_parameters(self):
        for options in ({"interval": 0}, {"interval": float("nan")},
                        {"repetitions": 10001}, {"ring": 4000}, {"mode": "unknown"}):
            with self.assertRaises(ValueError):
                run_session(**options)


@unittest.skipUnless(os.name == "posix", "POSIX owned child and signal tests")
class CleanupReliabilityTests(unittest.TestCase):
    def test_keyboard_interrupt_reaps_owned_child(self):
        created = []
        real_popen = subprocess.Popen
        def spawn(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            created.append(child)
            real_wait = child.wait
            called = False
            def wait(*args, **kwargs):
                nonlocal called
                if not called:
                    called = True
                    raise KeyboardInterrupt
                return real_wait(*args, **kwargs)
            child.wait = wait
            return child
        with patch("kirabridge_monitor.probe.subprocess.Popen", side_effect=spawn):
            with self.assertRaises(KeyboardInterrupt):
                wait_owned([sys.executable, "-I", "-c", "import time; time.sleep(10)"], 3)
        self.assertIsNotNone(created[0].returncode)

    def test_cleanup_failure_is_visible(self):
        class Child:
            def poll(self):
                return None
            def kill(self):
                pass
            def wait(self, timeout):
                raise subprocess.TimeoutExpired("synthetic", timeout)
        with patch("kirabridge_monitor.probe.subprocess.Popen", return_value=Child()):
            result = wait_owned(["synthetic"], 0.001)
        self.assertEqual(result["status"], "timeout")
        self.assertFalse(result["cleanup_ok"])

    def test_sigterm_cli_writes_summary_and_incomplete_footer(self):
        root = Path(__file__).resolve().parents[1] / ".tmp"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temp:
            child = subprocess.Popen([sys.executable, "-m", "kirabridge_monitor", "monitor",
                                      "--output", temp, "--duration", "60", "--marker"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 8
                incidents = []
                while time.monotonic() < deadline:
                    incidents = list(Path(temp).glob("run-*/incidents.jsonl"))
                    if incidents and incidents[0].stat().st_size:
                        break
                    if child.poll() is not None:
                        self.fail("test monitor exited before ready")
                    time.sleep(0.01)  # condition with deadline, not fixed readiness assumption
                self.assertTrue(incidents and incidents[0].stat().st_size)
                child.send_signal(signal.SIGTERM)  # exactly our test monitor
                stdout, stderr = child.communicate(timeout=8)
                self.assertEqual(child.returncode, 130, stderr)
                result = json.loads(stdout)
                self.assertTrue(result["interrupted"])
                self.assertTrue(result["worker_stopped"])
                self.assertTrue(result["incomplete_post_window"])
                lines = [json.loads(line) for line in incidents[0].read_text().splitlines()]
                self.assertFalse(lines[-1]["post_window_complete"])
                self.assertEqual(lines[0]["run_id"], result["run_id"])
            finally:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=3)


if __name__ == "__main__":
    unittest.main()
