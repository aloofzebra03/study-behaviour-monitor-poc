"""Run with python -m unittest discover -s tests -v. No camera required."""

import json
import unittest
from unittest.mock import patch

from study_monitor.rules import OFF_TASK, STUDYING, UNKNOWN, RuleEngine, Settings
from study_monitor.telemetry import parse_measurement
from study_monitor.usb import FreshnessGate, Received, UsbReader, list_devices


def sample(t, yaw=0, pitch=0, count=1, run="run-a", seq=None):
    return parse_measurement(json.dumps({
        "schema_version": 1, "run_id": run, "sequence": round(t * 10) if seq is None else seq,
        "capture_ms": round(t * 1000), "face_count": count,
        "yaw": yaw if count == 1 else None, "pitch": pitch if count == 1 else None,
        "roll": 0 if count == 1 else None, "bounds": [0.2, 0.2, 0.8, 0.8] if count == 1 else None,
        "error": None,
    }))


class TelemetryTests(unittest.TestCase):
    def test_single_face(self):
        self.assertTrue(sample(1).usable)

    def test_no_or_multiple_faces_are_unavailable(self):
        self.assertFalse(sample(1, count=0).usable)
        self.assertFalse(sample(1, count=2).usable)

    def test_invalid_contracts(self):
        base = sample(1).as_dict()
        for update in ({"schema_version": 2}, {"yaw": float("nan")}, {"yaw": None},
                       {"bounds": [0.9, 0.2, 0.1, 0.8]}, {"sequence": True},
                       {"face_count": 2}, {"capture_ms": -1}, {"face_count": None}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                parse_measurement(json.dumps({**base, **update}))
        for text in ("not-json", "[]", "x" * 4097):
            with self.assertRaises(ValueError):
                parse_measurement(text)

    def test_explicit_detector_failure(self):
        base = sample(1, count=0).as_dict()
        self.assertFalse(parse_measurement(json.dumps({**base, "face_count": None, "error": "detector_error"})).usable)


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.engine = RuleEngine()
        self.engine.profiles = {"screen": {"yaw": 0, "pitch": 0}, "notebook": {"yaw": 0, "pitch": -30}}
        self.engine.update_settings(Settings(smoothing_alpha=1))

    def feed(self, start, end, **kwargs):
        for tick in range(round(start * 5), round(end * 5) + 1):
            self.engine.process(sample(tick / 5, **kwargs))

    def test_screen_and_notebook_are_accepted(self):
        self.feed(1, 3.2)
        self.assertEqual(self.engine.status, STUDYING)
        self.feed(3.4, 6, pitch=-30)
        self.assertEqual(self.engine.status, STUDYING)
        self.assertEqual(self.engine.matched_position, "notebook")

    def test_brief_glance_then_sustained_turn_then_recovery(self):
        self.feed(1, 3.2)
        self.feed(3.4, 5, yaw=40)
        self.assertEqual(self.engine.status, STUDYING)
        self.feed(5.2, 6)
        self.feed(6.2, 11.4, yaw=40)
        self.assertEqual(self.engine.status, OFF_TASK)
        self.feed(11.6, 13.8)
        self.assertEqual(self.engine.status, STUDYING)

    def test_unknown_resets_candidates(self):
        for count in (0, 2):
            self.feed(1, 5.8, yaw=45)
            self.engine.process(sample(6, count=count))
            self.assertEqual(self.engine.status, UNKNOWN)
            self.assertIsNone(self.engine.candidate_since)
            self.feed(6.2, 7, yaw=45)
            self.assertNotEqual(self.engine.status, OFF_TASK)
            self.engine = RuleEngine()
            self.engine.profiles = {"screen": {"yaw": 0, "pitch": 0}, "notebook": {"yaw": 0, "pitch": -30}}
            self.engine.update_settings(Settings(smoothing_alpha=1))

    def test_gap_and_restart_cannot_complete_old_timer(self):
        self.feed(1, 5.8, yaw=45)
        self.engine.process(sample(10, yaw=45))
        self.assertEqual(self.engine.status, UNKNOWN)
        self.assertEqual(self.engine.elapsed, 0)
        self.feed(10.2, 14.8, yaw=45)
        self.engine.process(sample(15, yaw=45, run="new-run"))
        self.assertEqual(self.engine.elapsed, 0)
        self.assertEqual(self.engine.status, UNKNOWN)

    def test_duplicates_do_not_advance_timer(self):
        self.engine.process(sample(1, yaw=45))
        self.assertFalse(self.engine.process(sample(9, yaw=45, seq=10)))
        self.assertEqual(self.engine.elapsed, 0)

    def test_settings_and_pause_reset_timers(self):
        self.feed(1, 5.8, yaw=45)
        self.engine.update_settings(Settings(away_seconds=4, smoothing_alpha=1))
        self.assertEqual(self.engine.status, UNKNOWN)
        self.assertIsNone(self.engine.candidate_since)
        self.engine.process(sample(6, yaw=45))
        self.assertEqual(self.engine.elapsed, 0)
        self.engine.reset("Paused")
        self.assertIsNone(self.engine.smoothed)

    def test_calibration_uses_five_seconds_and_median(self):
        self.engine.clear_calibration()
        self.engine.begin_calibration("screen")
        self.feed(1, 6, yaw=4, pitch=2)
        self.assertEqual(self.engine.profiles["screen"], {"yaw": 4, "pitch": 2})
        self.assertEqual(self.engine.status, UNKNOWN)
        self.engine.begin_calibration("notebook")
        self.feed(6.2, 11.4, pitch=-30)
        self.assertIn("notebook", self.engine.profiles)

    def test_interrupted_calibration_does_not_save_partial_data(self):
        self.engine.clear_calibration()
        self.engine.begin_calibration("screen")
        self.feed(1, 4)
        self.engine.process(sample(4.2, count=0))
        self.feed(4.4, 7)
        self.assertNotIn("screen", self.engine.profiles)
        self.assertIsNotNone(self.engine.calibration)

    def test_unstable_calibration_retries(self):
        self.engine.clear_calibration()
        self.engine.begin_calibration("screen")
        self.feed(1, 3.4, yaw=-15)
        self.feed(3.6, 6, yaw=15)
        self.assertNotIn("screen", self.engine.profiles)
        self.assertIn("movement", self.engine.calibration_message)

    def test_calibration_required(self):
        self.engine.clear_calibration()
        self.feed(1, 10)
        self.assertEqual(self.engine.status, UNKNOWN)


class UsbTests(unittest.TestCase):
    def test_freshness_duplicate_history_and_old_runs(self):
        gate = FreshnessGate(1000, 100)
        self.assertEqual(gate.accept(sample(0.9), 100), (False, "historical"))
        self.assertTrue(gate.accept(sample(1.2), 100.2)[0])
        self.assertFalse(gate.accept(sample(1.2), 100.3)[0])
        self.assertFalse(gate.accept(sample(1.1, seq=100), 100.3)[0])
        self.assertFalse(gate.accept(sample(1.4), 103)[0])
        self.assertTrue(gate.accept(sample(1.6, run="new"), 100.6)[0])
        self.assertFalse(gate.accept(sample(1.8), 100.8)[0])

    def test_clock_mismatch_is_rejected(self):
        gate = FreshnessGate(1000, 100)
        self.assertFalse(gate.accept(sample(20), 101)[0])

    def test_slow_dashboard_discards_backlog(self):
        reader = UsbReader("unused", "phone")
        reader._last_consumer = 100
        reader.events.put(Received(sample(1), 100.2))
        reader.events.put(Received(sample(2), 102))
        with patch("study_monitor.usb.time.monotonic", return_value=102.1):
            events, reset = reader.drain()
        self.assertTrue(reset)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].measurement.capture_ms, 2000)

    def test_recent_batch_and_overflow_are_handled(self):
        reader = UsbReader("unused", "phone")
        reader._last_consumer = 100
        for t in (100.1, 100.3):
            reader.events.put(Received(sample(t), t))
        with patch("study_monitor.usb.time.monotonic", return_value=100.4):
            batch, reset = reader.drain()
        self.assertEqual(len(batch), 2)
        self.assertFalse(reset)
        reader._overflowed = True
        reader.events.put(Received(sample(101), 101))
        with patch("study_monitor.usb.time.monotonic", return_value=101):
            _, reset = reader.drain()
        self.assertTrue(reset)

    def test_device_states(self):
        with patch("study_monitor.usb.command") as mocked:
            mocked.return_value.returncode = 0
            mocked.return_value.stdout = "List of devices attached\na device product:a\nb unauthorized\nc offline\n"
            devices = list_devices("adb")
        self.assertEqual([d["state"] for d in devices], ["device", "unauthorized", "offline"])

    def test_reader_stops_its_own_process(self):
        from unittest.mock import MagicMock
        reader = UsbReader("unused", "phone")
        reader._process = MagicMock()
        reader._process.poll.return_value = None
        reader.stop()
        reader._process.terminate.assert_called_once()

    def test_reader_rejects_history_and_invalid_lines(self):
        from unittest.mock import MagicMock
        reader = UsbReader("adb", "phone")
        reader._last_consumer = 100
        process = MagicMock()
        process.poll.return_value = 0
        with patch("study_monitor.usb.list_devices", return_value=[{"serial": "phone", "state": "device"}]), \
             patch("study_monitor.usb.command") as adb_call, \
             patch("study_monitor.usb.subprocess.Popen", return_value=process), \
             patch("study_monitor.usb.time.monotonic", return_value=100.2):
            adb_call.return_value.returncode = 0
            adb_call.return_value.stdout = "1.0 1.0"
            # Use a closable iterator, just like the Popen stream.
            from io import StringIO
            process.stdout = StringIO("\n".join(["{broken", json.dumps(sample(0.5).as_dict()),
                                                   json.dumps(sample(1.2).as_dict()), json.dumps(sample(1.2).as_dict())]))
            with self.assertLogs("study_monitor.usb", level="ERROR"):
                reader._run()
        self.assertEqual(reader.snapshot()["accepted"], 1)
        self.assertEqual(reader.snapshot()["discarded"], 3)
        self.assertIn("exited", reader.snapshot()["error"])
        self.assertEqual(reader.events.get_nowait().measurement.capture_ms, 1200)


if __name__ == "__main__":
    unittest.main()
