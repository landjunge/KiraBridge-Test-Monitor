"""Single writer event loop; independent probe worker never touches other sessions."""
from contextlib import ExitStack
import platform
import math
import queue
import random
import signal
import threading
import time

from . import __version__
from .clock import Clock
from .metrics import Sampler
from .probe import SCENARIOS, probe_once
from .report import Summary
from .storage import BlackBox, CSVWriter, RotatingWriter, run_directory


PROBE_FIELDS = ["run_id", "probe_index", "scenario", "started_utc", "utc",
                "started_monotonic_ns", "monotonic_ns", "duration_ns", "status",
                "exit_code", "timeout_seconds", "cleanup_ok", "input_bytes", "output_bytes"]


def write_json(path, value):
    writer = RotatingWriter(path, max_bytes=65536, backups=0)
    try:
        writer.json(value)
    finally:
        writer.close()


def run_session(*, mode="logging", output="runs", interval=1.0, duration=60.0,
                repetitions=None, scenario="noop", timeout=2.0, ring=120, post=10.0,
                max_bytes=1048576, backups=3, windows=1, codex_instances=None,
                marker=False):
    if mode not in ("off", "memory", "logging") or scenario not in SCENARIOS:
        raise ValueError("invalid session mode or scenario")
    if not all(math.isfinite(v) for v in (interval, duration, timeout, post)):
        raise ValueError("nonfinite session parameter")
    if interval <= 0 or duration <= 0 or timeout <= 0 or not 0 <= post <= 60:
        raise ValueError("invalid session timing")
    if repetitions is not None and not 1 <= repetitions <= 10000:
        raise ValueError("invalid probe count")
    if not 1 <= ring <= 3600 or not 16384 <= max_bytes <= 16777216 or not 0 <= backups <= 10:
        raise ValueError("invalid storage bounds")
    clock = Clock()
    summary = Summary()
    stop = threading.Event()
    messages = queue.Queue(maxsize=128)
    producer = None
    directory = None
    interrupted = False
    incomplete_post_window = False
    started = time.monotonic()
    cpu_started = time.process_time()
    sample_writer = event_writer = csv_writer = None
    box = BlackBox(capacity=ring, post_seconds=post, clock=clock)
    # Ctrl-C is supported everywhere; SIGTERM on CLI main thread uses same cleanup.
    previous_sigterm = None
    if threading.current_thread() is threading.main_thread():
        previous_sigterm = signal.getsignal(signal.SIGTERM)
        def terminate(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, terminate)

    def emit(item):
        while not stop.is_set():
            try:
                messages.put(item, timeout=0.1)
                return
            except queue.Full:
                continue

    def produce():
        try:
            for index in range(repetitions):
                if stop.is_set():
                    break
                record = probe_once(scenario, timeout, clock, stop)
                record["probe_index"] = index + 1
                emit(record)
        except Exception:
            # Fixed failure kind only: exceptions may carry private local paths.
            emit({"kind": "worker_error", **clock.stamp()})
        finally:
            emit({"kind": "worker_done"})

    def record(item):
        nonlocal sequence
        sequence += 1
        item["sequence"] = sequence
        summary.add(item)
        if event_writer and item["kind"] != "sample":
            event_writer.json(item)
        if sample_writer and item["kind"] == "sample":
            sample_writer.json(item)
        if csv_writer and item["kind"] == "probe":
            csv_writer.record(item)
        box.observe(item)
        if item.get("reason"):
            box.trigger(item)

    worker_done = repetitions is None
    worker_failed = False
    sequence = 0
    try:
        with ExitStack() as stack:
            if mode == "logging":
                directory = run_directory(output)
                def stream(name, cls=RotatingWriter, **extra):
                    writer = cls(directory / name, max_bytes=max_bytes, backups=backups, **extra)
                    stack.callback(writer.close)
                    return writer
                sample_writer = stream("samples.jsonl")
                event_writer = stream("events.jsonl")
                csv_writer = stream("probes.csv", CSVWriter, fields=PROBE_FIELDS)
                box.writer = stream("incidents.jsonl")
                write_json(directory / "metadata.json", {
                    **clock.stamp(), "kind": "metadata", "version": __version__,
                    "python": platform.python_version(), "os": platform.system(),
                    "os_release": platform.release(), "architecture": platform.machine(),
                    "mode": mode, "interval_seconds": interval, "duration_seconds": duration,
                    "repetitions": repetitions, "scenario": scenario, "timeout_seconds": timeout,
                    "ring_records": ring, "post_seconds": post, "max_bytes": max_bytes,
                    "backups": backups, "declared_windows": windows,
                    "declared_codex_instances": codex_instances,
                    "warmup": "first CPU/rates null; no probe excluded",
                    "clock_scope": "monotonic values only comparable within run_id",
                })
            def finish_box():
                nonlocal incomplete_post_window
                incomplete_post_window = box.active is not None
                box.finish(complete=False)
            stack.callback(finish_box)  # footer before stream handles close
            sampler = Sampler(clock) if mode != "off" else None
            next_sample = time.monotonic()
            if sampler:
                record(sampler.sample())
                next_sample += interval
            if marker:
                record({**clock.stamp(), "kind": "event", "reason": "manual_marker"})
            if repetitions is not None:
                producer = threading.Thread(target=produce, name="synthetic-probe", daemon=True)
                producer.start()
            deadline = started + duration
            while True:
                now = time.monotonic()
                if repetitions is None:
                    if now >= deadline:
                        break
                elif worker_done and messages.empty() and not box.active:
                    break
                if sampler and now >= next_sample:
                    sample = sampler.sample()
                    record(sample)
                    if sample["elapsed_seconds"] is not None and sample["elapsed_seconds"] > 2 * interval:
                        record({**clock.stamp(), "kind": "event", "reason": "sampling_gap"})
                    # No catch-up burst after a slow sample/write.
                    next_sample = max(next_sample + interval, time.monotonic() + 0.001)
                wake_at = []
                if sampler:
                    wake_at.append(next_sample)
                if repetitions is None:
                    wake_at.append(deadline)
                if box.active:
                    wake_at.append(box.active["deadline_ns"] / 1e9)
                wait = max(0, min(wake_at) - time.monotonic()) if wake_at else None
                try:
                    item = messages.get(timeout=wait)
                except queue.Empty:
                    # Even mode off must finish an incident post-window.
                    if box.active and time.monotonic_ns() >= box.active["deadline_ns"]:
                        box.finish(complete=True)
                    continue
                if item["kind"] == "worker_done":
                    worker_done = True
                    continue
                if item["kind"] == "worker_error":
                    worker_failed = True
                record(item)
                if item["kind"] == "probe" and item["status"] not in ("ok", "cancelled"):
                    reason = "probe_timeout" if item["status"] == "timeout" else "probe_error"
                    record({**clock.stamp(), "kind": "event", "reason": reason,
                            "probe_index": item["probe_index"]})
    except KeyboardInterrupt:
        interrupted = True
    finally:
        stop.set()
        if producer:
            producer.join(timeout=3)
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
    result = summary.report()
    result.update(run_id=clock.run_id, mode=mode, scenario=scenario,
                  declared_windows=windows, declared_codex_instances=codex_instances,
                  interrupted=interrupted, worker_failed=worker_failed or (
                      repetitions is not None and not interrupted and result["probe_count"] != repetitions),
                  worker_stopped=producer is None or not producer.is_alive(),
                  wall_seconds=time.monotonic() - started,
                  own_cpu_seconds=time.process_time() - cpu_started,
                  incidents=box.incidents, incomplete_post_window=incomplete_post_window,
                  directory=str(directory) if directory else None)
    if directory:
        write_json(directory / "summary.json", {**result, "directory": directory.name})
    return result


def overhead(*, repetitions=100, rounds=2, seed=20261029, **options):
    """Seeded order, all three conditions each round. No synthetic system load."""
    rng = random.Random(seed)
    trials = []
    for round_index in range(rounds):
        modes = ["off", "memory", "logging"]
        rng.shuffle(modes)
        for mode in modes:
            result = run_session(mode=mode, repetitions=repetitions, **options)
            result["round"] = round_index + 1
            trials.append(result)
            if result["interrupted"]:
                return {"seed": seed, "rounds": rounds, "trials": trials, "interrupted": True}
    return {"seed": seed, "rounds": rounds, "trials": trials, "interrupted": False}
