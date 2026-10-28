"""Read only our app's numeric telemetry. No network receiver is involved."""

import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass

from .telemetry import Measurement, parse_measurement

LOG = logging.getLogger(__name__)
TAG = "StudyMonitor"


def command(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, timeout=8,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **kwargs)


def find_adb(configured=""):
    candidate = configured.strip() or os.environ.get("ADB_PATH", "") or shutil.which("adb")
    if candidate and os.path.isfile(candidate):
        return os.path.abspath(candidate)
    raise FileNotFoundError("ADB not found. Install Android SDK Platform Tools and enter the full path to adb.exe.")


def list_devices(adb):
    result = command([adb, "devices", "-l"])
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "ADB could not list devices.")
    devices = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] in ("device", "unauthorized", "offline"):
            devices.append({"serial": fields[0], "state": fields[1], "description": " ".join(fields[2:])})
    return devices


class FreshnessGate:
    """Map Android elapsedRealtime to host monotonic time, not wall clocks."""

    def __init__(self, phone_ms, host_time):
        self.phone_ms = phone_ms
        self.host_time = host_time
        self.last = None
        self.retired_runs = set()

    def capture_time(self, item):
        return self.host_time + (item.capture_ms - self.phone_ms) / 1000

    def accept(self, item, received_at):
        if item.capture_ms < self.phone_ms:
            return False, "historical"
        age = received_at - self.capture_time(item)
        if age > 1 or age < -0.5:
            return False, "stale_or_clock_mismatch"
        if item.run_id in self.retired_runs:
            return False, "retired_run"
        if self.last:
            if item.run_id == self.last.run_id:
                if item.sequence <= self.last.sequence or item.capture_ms <= self.last.capture_ms:
                    return False, "duplicate_or_out_of_order"
            else:
                self.retired_runs.add(self.last.run_id)
        self.last = item
        return True, "accepted"


@dataclass(frozen=True)
class Received:
    measurement: Measurement
    capture_time: float


class UsbReader:
    def __init__(self, adb, serial):
        self.adb = adb
        self.serial = serial
        self.events = queue.Queue(maxsize=64)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._finished = threading.Event()
        self._thread = None
        self._process = None
        self._status = "Not connected"
        self._error = ""
        self._accepted = 0
        self._dropped = 0
        self._overflowed = False
        self._last_received = None
        self._last_consumer = time.monotonic()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"study-usb-{self.serial}")
        self._thread.start()

    def _set_status(self, status, error=""):
        with self._lock:
            self._status, self._error = status, error
        LOG.info("USB %s: %s %s", self.serial, status, error)

    def _run(self):
        process = None
        watchdog = threading.Thread(target=self._watch_inactivity, daemon=True)
        watchdog.start()
        try:
            self._set_status("Connecting")
            devices = list_devices(self.adb)
            device = next((d for d in devices if d["serial"] == self.serial), None)
            if not device:
                raise RuntimeError("Phone disconnected. Connect the USB cable and refresh devices.")
            if device["state"] != "device":
                raise RuntimeError(f"Phone is {device['state']}. Unlock it and approve the USB debugging prompt.")
            before = time.monotonic()
            uptime = command([self.adb, "-s", self.serial, "shell", "cat", "/proc/uptime"])
            after = time.monotonic()
            if uptime.returncode or after - before > 1:
                raise RuntimeError("Could not synchronize phone uptime promptly. Reconnect and try again.")
            phone_ms = float(uptime.stdout.split()[0]) * 1000
            gate = FreshnessGate(phone_ms, (before + after) / 2)
            # Start from the tail, never clear global logs, and reject pre-connection captures.
            process = subprocess.Popen(
                [self.adb, "-s", self.serial, "logcat", "-b", "main", "-v", "raw", "-T", "1", f"{TAG}:I", "*:S"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            with self._lock:
                self._process = process
            if self._stop.is_set():
                return
            self._set_status("Connected — waiting for fresh app telemetry")
            for line in process.stdout:
                if self._stop.is_set():
                    break
                # Don't leave an orphan reader after a dashboard tab closes.
                if time.monotonic() - self._last_consumer > 120:
                    self._set_status("Disconnected — dashboard inactive")
                    break
                line = line.strip()
                if not line or line.startswith("---------"):
                    continue
                if not line.startswith("{"):
                    if "error:" in line.lower() or "device offline" in line.lower():
                        raise RuntimeError("ADB connection interrupted. Reconnect the phone and dashboard.")
                    continue
                now = time.monotonic()
                try:
                    item = parse_measurement(line)
                    accepted, reason = gate.accept(item, now)
                except (ValueError, TypeError, KeyError):
                    accepted, reason = False, "invalid_json_contract"
                if not accepted:
                    with self._lock:
                        self._dropped += 1
                    LOG.debug("Discarded telemetry: %s", reason)
                    continue
                with self._lock:
                    self._accepted += 1
                    self._last_received = now
                    self._status = "Receiving measurements"
                event = Received(item, gate.capture_time(item))
                try:
                    self.events.put_nowait(event)
                except queue.Full:
                    with self._lock:
                        self._overflowed = True
                    try:
                        self.events.get_nowait()
                    except queue.Empty:
                        pass
                    self.events.put_nowait(event)
            if not self._stop.is_set() and process.poll() is not None:
                raise RuntimeError("ADB log reader exited. Reconnect the dashboard; check USB authorization.")
        except Exception as exc:
            LOG.exception("USB reader stopped")
            self._set_status("Connection failed", str(exc))
        finally:
            if process:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
                if process.stdout:
                    process.stdout.close()
            with self._lock:
                self._process = None
                if self._stop.is_set():
                    self._status = "Disconnected"
            self._finished.set()

    def _watch_inactivity(self):
        # stdout can block forever when the phone app is stopped, so this cannot
        # depend on another telemetry line arriving.
        while not self._finished.wait(1):
            with self._lock:
                inactive = time.monotonic() - self._last_consumer > 120
            if inactive:
                self._set_status("Disconnected — dashboard inactive")
                self._stop.set()
                with self._lock:
                    process = self._process
                if process and process.poll() is None:
                    process.terminate()
                return

    def drain(self):
        now = time.monotonic()
        with self._lock:
            gap = self._overflowed or now - self._last_consumer > 1
            self._overflowed = False
            self._last_consumer = now
        events = []
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if now - event.capture_time > 1:
                gap = True
            else:
                events.append(event)
        # Backlogged transitions must not contribute to a continuous observation.
        return (events[-1:] if gap else events), gap

    def snapshot(self):
        with self._lock:
            return {"status": self._status, "error": self._error, "accepted": self._accepted,
                    "discarded": self._dropped, "last_received": self._last_received,
                    "alive": bool(self._thread and self._thread.is_alive())}

    def stop(self):
        self._stop.set()
        with self._lock:
            process = self._process
        if process and process.poll() is None:
            process.terminate()
        if self._thread:
            self._thread.join(timeout=3)
