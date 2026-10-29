"""Synthetic local probes. No user command, terminal content or output capture."""
import os
import shlex
import subprocess
import sys
import time


SCENARIOS = {
    "noop": (0, 0),
    "long-input": (16384, 0),
    "output-4k": (0, 4096),
    "output-1m": (0, 1048576),
}


def command(scenario):
    if os.name != "posix":
        raise NotImplementedError("terminal probes currently require POSIX")
    if scenario == "noop":
        script = ":"
    elif scenario == "long-input":
        script = ": " + "x" * SCENARIOS[scenario][0]
    elif scenario in ("output-4k", "output-1m"):
        size = SCENARIOS[scenario][1]
        # exec replaces our shell: there is exactly one owned process to clean up.
        code = "import sys; sys.stdout.buffer.write(b'x'*%d)" % size
        script = "exec %s -I -c %s" % (shlex.quote(sys.executable), shlex.quote(code))
    else:
        raise ValueError("unknown synthetic scenario")
    return ["/bin/sh", "-c", script]


def wait_owned(argv, timeout, cancelled=None):
    """Internal helper; only signal/reap the Popen object created in this call."""
    start = time.monotonic_ns()
    process = None
    status, exit_code = "spawn_error", None
    cleanup_ok = True
    try:
        # Discard both streams at the OS boundary. Never hold their bytes in Python.
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   env={"PATH": os.defpath}, close_fds=True)
        deadline = start + int(timeout * 1e9)
        while True:
            if cancelled is not None and cancelled.is_set():
                status = "cancelled"
                break
            remaining = (deadline - time.monotonic_ns()) / 1e9
            if remaining <= 0:
                # A process that actually exited is successful even at the boundary.
                exit_code = process.poll()
                status = ("ok" if exit_code == 0 else "error") if exit_code is not None else "timeout"
                break
            try:
                exit_code = process.wait(timeout=min(remaining, 0.1))
                status = "ok" if exit_code == 0 else "error"
                break
            except subprocess.TimeoutExpired:
                continue
    except OSError:
        status = "spawn_error"  # never persist exception text or executable paths
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                cleanup_ok = False
    return {"status": status, "exit_code": exit_code,
            "duration_ns": time.monotonic_ns() - start,
            "cleanup_ok": cleanup_ok}


def probe_once(scenario, timeout, clock, cancelled=None):
    start = clock.stamp()
    result = wait_owned(command(scenario), timeout, cancelled)
    result.update(clock.stamp())
    input_bytes, output_bytes = SCENARIOS[scenario]
    result.update(kind="probe", scenario=scenario, timeout_seconds=timeout,
                  started_monotonic_ns=start["monotonic_ns"], started_utc=start["utc"],
                  input_bytes=input_bytes, output_bytes=output_bytes)
    return result
