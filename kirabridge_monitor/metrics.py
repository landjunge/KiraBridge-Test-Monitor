"""Read-only sampling; persist categories, never process names or arguments."""
import ctypes
from datetime import datetime
import os
import platform
import time

import psutil


READ_ERRORS = (psutil.Error, OSError, AttributeError, NotImplementedError)


def memory_pressure():
    """Darwin's kernel pressure level, NOT free RAM relabelled as pressure."""
    if platform.system() != "Darwin":
        return None, "unsupported"
    try:
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        value = ctypes.c_int()
        size = ctypes.c_size_t(ctypes.sizeof(value))
        call = libc.sysctlbyname
        call.argtypes = [ctypes.c_char_p, ctypes.c_void_p,
                         ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p,
                         ctypes.c_size_t]
        call.restype = ctypes.c_int
        if call(b"kern.memorystatus_vm_pressure_level", ctypes.byref(value),
                ctypes.byref(size), None, 0) != 0:
            return None, "unavailable"
        label = {1: "normal", 2: "warning", 4: "critical"}.get(value.value)
        return label, "ok" if label else "unavailable"
    except (OSError, AttributeError):
        return None, "unavailable"


def category(name):
    """Fixed labels prevent process names (possibly private) reaching disk."""
    name = name.lower()
    if "codex" in name:
        return "codex"
    if "kirabridge" in name:
        return "kirabridge"
    if name in ("terminal", "iterm2", "windowserver", "tmux"):
        return "terminal_display"
    if any(s in name for s in ("chrome", "firefox", "safari", "webkit")):
        return "browser"
    if name in ("mds", "mds_stores", "mdworker", "mdworker_shared"):
        return "spotlight"
    if name in ("backupd", "backupd-helper"):
        return "backup"
    return "other_busy"


def counter_rates(current, previous, seconds):
    """Missing counters and resets produce null, not misleading zero rates."""
    return {key: ((value - previous[key]) / seconds
                  if seconds and seconds > 0 and value is not None
                  and previous.get(key) is not None and value >= previous[key]
                  else None) for key, value in current.items()}


class Sampler:
    def __init__(self, clock, process_interval=5.0, api=psutil):
        self.clock = clock
        self.api = api
        self.process_interval = process_interval
        self.previous_time = None
        self.previous_wall = None
        self.previous_counters = {}
        self.previous_cpu = None
        self.process_time = None
        self.process_cpu = {}
        self.process_data = None
        self.process_status = "warming_up"
        self.self_process = api.Process(os.getpid())
        self.self_cpu = None

    def _read(self, status, key, fn):
        try:
            value = fn()
            status[key] = "ok" if value is not None else "unavailable"
            return value
        except READ_ERRORS:
            status[key] = "unavailable"
            return None

    def _processes(self, now):
        if self.process_time is not None and now - self.process_time < self.process_interval:
            return
        elapsed = now - self.process_time if self.process_time is not None else None
        current = {}
        groups = {}
        skipped = 0
        try:
            for proc in self.api.process_iter():
                try:
                    with proc.oneshot():
                        # Read only name, creation time and resource counters.
                        name = proc.name()
                        identity = (proc.pid, proc.create_time())
                        times = proc.cpu_times()
                        cpu = times.user + times.system
                        rss = proc.memory_info().rss
                    prior = self.process_cpu.get(identity)
                    percent = ((cpu - prior) * 100 / elapsed
                               if elapsed and prior is not None and cpu >= prior else None)
                    current[identity] = cpu
                    group = category(name)
                    if group == "other_busy" and not (percent is not None and percent >= 5):
                        continue
                    bucket = groups.setdefault(group, {"count": 0, "rss_bytes": 0,
                                                       "cpu_percent": None})
                    bucket["count"] += 1
                    bucket["rss_bytes"] += rss
                    if percent is not None:
                        bucket["cpu_percent"] = (bucket["cpu_percent"] or 0) + percent
                except READ_ERRORS:
                    skipped += 1
            self.process_data = {"groups": groups, "skipped": skipped}
            self.process_status = "partial" if skipped else "ok"
        except READ_ERRORS:
            self.process_data = None
            self.process_status = "unavailable"
        self.process_cpu = current  # prune exited processes each scan
        self.process_time = now

    def sample(self):
        started = time.monotonic_ns()
        result = self.clock.stamp()
        now = result["monotonic_ns"] / 1e9
        wall = datetime.fromisoformat(result["utc"].replace("Z", "+00:00")).timestamp()
        elapsed = now - self.previous_time if self.previous_time is not None else None
        status = {}
        metrics = {}
        cpu = self._read(status, "cpu", self.api.cpu_times)
        if cpu is not None:
            fields = cpu._asdict()
            total = sum(fields.values()) - fields.get("guest", 0) - fields.get("guest_nice", 0)
            idle = fields.get("idle", 0) + fields.get("iowait", 0)
            prior = self.previous_cpu
            delta = total - prior[0] if prior is not None else 0
            valid = (delta > 0 and idle >= prior[1]
                     and (total - idle) >= (prior[0] - prior[1]))
            metrics["cpu_percent"] = (max(0, min(100, 100 * (1 - (idle - prior[1]) / delta)))
                                      if valid else None)
            self.previous_cpu = (total, idle)
        else:
            metrics["cpu_percent"] = None
            self.previous_cpu = None
        vm = self._read(status, "memory", self.api.virtual_memory)
        metrics.update(ram_total_bytes=vm.total if vm else None,
                       ram_available_bytes=vm.available if vm else None,
                       ram_percent=vm.percent if vm else None)
        swap = self._read(status, "swap", self.api.swap_memory)
        metrics.update(swap_used_bytes=swap.used if swap else None,
                       swap_total_bytes=swap.total if swap else None)
        disk = self._read(status, "disk", self.api.disk_io_counters)
        net = self._read(status, "network", self.api.net_io_counters)
        counters = {
            "disk_read_bytes": disk.read_bytes if disk else None,
            "disk_write_bytes": disk.write_bytes if disk else None,
            "net_sent_bytes": net.bytes_sent if net else None,
            "net_recv_bytes": net.bytes_recv if net else None,
            "swap_in_bytes": swap.sin if swap and platform.system() not in ("Windows", "OpenBSD") else None,
            "swap_out_bytes": swap.sout if swap and platform.system() not in ("Windows", "OpenBSD") else None,
        }
        status["swap_activity"] = ("unsupported" if platform.system() in ("Windows", "OpenBSD")
                                   else status["swap"])
        metrics.update(counters)
        metrics.update({key + "_per_second": value for key, value in
                        counter_rates(counters, self.previous_counters, elapsed).items()})
        pressure, pressure_status = memory_pressure()
        metrics["memory_pressure"] = pressure
        status["memory_pressure"] = pressure_status
        self._processes(now)
        status["processes"] = self.process_status
        own_cpu = self._read(status, "self_cpu", self.self_process.cpu_times)
        own_rss = self._read(status, "self_rss", lambda: self.self_process.memory_info().rss)
        own_total = own_cpu.user + own_cpu.system if own_cpu else None
        metrics["self_cpu_percent"] = ((own_total - self.self_cpu) * 100 / elapsed
                                       if elapsed and own_total is not None
                                       and self.self_cpu is not None and own_total >= self.self_cpu else None)
        metrics["self_rss_bytes"] = own_rss
        self.self_cpu = own_total
        result.update(kind="sample", metrics=metrics, status=status,
                      processes=self.process_data,
                      processes_age_seconds=now - self.process_time,
                      elapsed_seconds=elapsed,
                      wall_drift_seconds=(wall - self.previous_wall - elapsed)
                      if self.previous_wall is not None and elapsed is not None else None,
                      sampling_ns=time.monotonic_ns() - started)
        self.previous_time, self.previous_wall = now, wall
        self.previous_counters = counters
        return result
