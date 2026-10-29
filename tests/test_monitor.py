"""Run with python -m unittest discover -s tests -v. No camera required."""

import json
import unittest
from unittest.mock import patch

from study_monitor.rules import NORMAL, AWAY, UNKNOWN, PAUSED, RuleEngine, Settings
from study_monitor.telemetry import parse_measurement
from study_monitor.usb import FreshnessGate, Received, UsbReader, find_adb, list_devices


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
        self.engine.update_settings(Settings(smoothing_alpha=1))
        self.engine.study_positions = {
            "reading": {"yaw": -35, "pitch": -20},
            "writing": {"yaw": -40, "pitch": -45},
        }

    def feed(self, start, end, **kwargs):
        values = {"yaw": -35, "pitch": -20, **kwargs}
        for tick in range(round(start * 5), round(end * 5) + 1):
            self.engine.process(sample(tick / 5, **values))

    def test_both_study_positions_are_accepted(self):
        self.feed(1, 3.2)
        self.assertEqual(self.engine.status, NORMAL)
        self.feed(3.4, 6, yaw=-40, pitch=-45)
        self.assertEqual(self.engine.status, NORMAL)
        self.assertEqual(self.engine.matched_position, "writing")

    def test_left_right_front_and_elevation_are_relative_to_setup(self):
        for side, height, reading, writing in [
            ("front", "level", (0, -15), (0, -40)),
            ("left", "above", (-35, 10), (-40, -10)),
            ("right", "above", (35, 10), (40, -10)),
            ("left", "below", (-35, -35), (-40, -55)),
            ("right", "below", (35, -35), (40, -55)),
            ("front", "above", (0, 20), (0, -5)),
            ("front", "below", (0, -35), (0, -60)),
        ]:
            with self.subTest(side=side, height=height):
                self.engine = RuleEngine()
                self.engine.set_placement(side, height)
                self.engine.update_settings(Settings(smoothing_alpha=1))
                self.engine.study_positions = {
                    "reading": dict(zip(("yaw", "pitch"), reading)),
                    "writing": dict(zip(("yaw", "pitch"), writing)),
                }
                self.feed(1, 3.2, yaw=reading[0], pitch=reading[1])
                self.assertEqual(self.engine.status, NORMAL)
                self.feed(3.4, 6, yaw=writing[0], pitch=writing[1])
                self.assertEqual(self.engine.status, NORMAL)

    def test_facing_camera_is_not_automatically_studying(self):
        self.feed(1, 11.2, yaw=0, pitch=0)
        self.assertEqual(self.engine.status, AWAY)
        self.assertIsNone(self.engine.matched_position)

    def test_brief_glance_sustained_departure_and_recovery(self):
        self.feed(1, 3.2)
        self.feed(3.4, 5, yaw=40)
        self.assertEqual(self.engine.status, NORMAL)
        self.feed(5.2, 6)
        self.feed(6.2, 16.4, yaw=40)
        self.assertEqual(self.engine.status, AWAY)
        self.feed(16.6, 18.8)
        self.assertEqual(self.engine.status, NORMAL)

    def test_unknown_resets_candidates_without_accusing_student(self):
        for count in (0, 2):
            self.engine.reset("New check")
            self.engine.last_identity = None
            self.engine.last_capture_ms = None
            self.feed(1, 9.8, yaw=45)
            self.engine.process(sample(10, count=count))
            self.assertEqual(self.engine.status, UNKNOWN)
            self.assertIsNone(self.engine.candidate_since)
            self.feed(10.2, 11, yaw=45)
            self.assertNotEqual(self.engine.status, AWAY)

    def test_gap_and_restart_cannot_complete_old_timer(self):
        self.feed(1, 9.8, yaw=45)
        self.engine.process(sample(20, yaw=45))
        self.assertEqual(self.engine.status, UNKNOWN)
        self.assertEqual(self.engine.elapsed, 0)
        self.feed(20.2, 29.8, yaw=45)
        self.engine.process(sample(30, yaw=45, run="new-run"))
        self.assertEqual(self.engine.elapsed, 0)
        self.assertEqual(self.engine.status, UNKNOWN)

    def test_duplicates_do_not_advance_timer(self):
        self.engine.process(sample(1, yaw=45))
        self.assertFalse(self.engine.process(sample(19, yaw=45, seq=10)))
        self.assertEqual(self.engine.elapsed, 0)

    def test_settings_reset_timers(self):
        self.feed(1, 9.8, yaw=45)
        self.engine.update_settings(Settings(away_seconds=4, smoothing_alpha=1))
        self.assertEqual(self.engine.status, UNKNOWN)
        self.assertIsNone(self.engine.candidate_since)
        self.engine.process(sample(10, yaw=45))
        self.assertEqual(self.engine.elapsed, 0)

    def test_break_time_is_not_off_task_time(self):
        self.feed(1, 9.8, yaw=45)
        self.engine.set_paused(True)
        self.feed(10, 60, yaw=45)
        self.assertEqual(self.engine.status, PAUSED)
        self.assertIsNone(self.engine.snapshot()["is_in_study_position"])
        self.engine.set_paused(False)
        self.feed(60.2, 61, yaw=45)
        self.assertNotEqual(self.engine.status, AWAY)
        self.assertLess(self.engine.elapsed, 1)
        self.assertTrue(self.engine.ready)

    def test_setup_is_required_and_one_position_is_not_enough(self):
        self.engine.clear_positions()
        self.feed(1, 15)
        self.assertEqual(self.engine.status, UNKNOWN)
        self.assertFalse(self.engine.ready)
        self.engine.study_positions["reading"] = {"yaw": -35, "pitch": -20}
        self.feed(15.2, 18)
        self.assertFalse(self.engine.ready)
        self.assertEqual(self.engine.status, UNKNOWN)
        self.assertIn("writing", self.engine.reason)

    def test_calibrate_reading_and_writing(self):
        self.engine.clear_positions()
        self.engine.begin_calibration("reading")
        self.feed(1, 6)
        self.assertEqual(self.engine.study_positions["reading"], {"yaw": -35, "pitch": -20})
        self.assertFalse(self.engine.ready)
        self.engine.begin_calibration("writing")
        self.feed(6.2, 11.4, yaw=-40, pitch=-45)
        self.assertTrue(self.engine.ready)
        self.feed(11.6, 14)
        self.assertEqual(self.engine.status, NORMAL)

    def test_interrupted_calibration_does_not_save_partial_data(self):
        self.engine.clear_positions()
        self.engine.begin_calibration("reading")
        self.feed(1, 4)
        self.engine.process(sample(4.2, count=0))
        self.feed(4.4, 7)
        self.assertNotIn("reading", self.engine.study_positions)
        self.assertIsNotNone(self.engine.calibration)

    def test_capture_completes_at_exact_five_seconds_from_fractional_start(self):
        self.engine.clear_positions()
        self.engine.begin_calibration("writing")
        self.feed(6.2, 11.2, yaw=-40, pitch=-45)
        self.assertIsNone(self.engine.calibration)
        self.assertEqual(self.engine.study_positions["writing"], {"yaw": -40, "pitch": -45})

    def test_unstable_calibration_retries(self):
        self.engine.clear_positions()
        self.engine.begin_calibration("reading")
        self.feed(1, 3.4, yaw=-65)
        self.feed(3.6, 6, yaw=0)
        self.assertNotIn("reading", self.engine.study_positions)
        self.assertIn("movement", self.engine.calibration_message)

    def test_recapture_or_cancel_cannot_leave_old_reference_valid(self):
        self.engine.begin_calibration("reading")
        self.assertFalse(self.engine.ready)
        self.engine.cancel_calibration()
        self.assertNotIn("reading", self.engine.study_positions)
        self.assertFalse(self.engine.ready)

    def test_placement_change_invalidates_setup(self):
        self.engine.set_placement("right", "above")
        self.assertFalse(self.engine.ready)
        self.assertFalse(self.engine.study_positions)
        self.assertEqual(self.engine.status, UNKNOWN)
        self.assertFalse(self.engine.set_placement("right", "above"))
        with self.assertRaises(ValueError):
            self.engine.set_placement("behind", "above")

    def test_profile_thresholds_only_is_default(self):
        profile = self.engine.export_profile()
        other = RuleEngine()
        other.load_profile(json.loads(json.dumps(profile)))
        self.assertEqual(other.settings, self.engine.settings)
        self.assertFalse(other.ready)
        self.assertFalse(other.study_positions)

    def test_same_setup_profile_can_be_explicitly_reused(self):
        self.engine.placement = {"side": "left", "height": "above"}
        profile = json.loads(json.dumps(self.engine.export_profile()))
        other = RuleEngine()
        other.load_profile(profile, reuse_positions=True)
        self.assertTrue(other.ready)
        self.assertEqual(other.study_positions, self.engine.study_positions)
        self.assertEqual(other.placement, self.engine.placement)

    def test_old_phone_facing_profile_never_becomes_study_setup(self):
        old = {"schema_version": 2, "reference_source": "captured", "settings": {
            "yaw_tolerance": 22, "pitch_tolerance": 16, "away_seconds": 5,
            "recovery_seconds": 2, "smoothing_alpha": 0.3, "center_yaw": 0, "center_pitch": 0}}
        self.engine.load_profile(old, reuse_positions=True)
        self.assertEqual(self.engine.settings.yaw_tolerance, 22)
        self.assertFalse(self.engine.ready)
        self.assertFalse(self.engine.study_positions)

    def test_invalid_profiles_do_not_change_settings(self):
        original = self.engine.export_profile()
        for bad in (
            {"schema_version": 1},
            {**original, "placement": {"side": "behind", "height": "level"}},
            {**original, "settings": {"yaw_tolerance": 20}},
            {**original, "settings": {**original["settings"], "yaw_tolerance": float("nan")}},
            {**original, "study_positions": {"reading": {"yaw": True, "pitch": 0}}},
            {**original, "study_positions": {"screen": {"yaw": 0, "pitch": 0}}},
        ):
            with self.subTest(bad=bad), self.assertRaises((ValueError, TypeError)):
                self.engine.load_profile(bad, reuse_positions=True)
            self.assertEqual(self.engine.export_profile(), original)

    def test_break_cancels_capture_and_prevents_calibration(self):
        self.engine.begin_calibration("reading")
        self.engine.set_paused(True)
        self.assertIsNone(self.engine.calibration)
        with self.assertRaises(ValueError):
            self.engine.begin_calibration("writing")

    def test_angle_wrap_does_not_create_false_zero_reference(self):
        from study_monitor.rules import median_angle
        self.assertGreater(abs(median_angle([179, -179, 178, -178])), 175)


class UsbTests(unittest.TestCase):
    def test_explicit_invalid_adb_path_has_clear_error(self):
        with self.assertRaisesRegex(FileNotFoundError, "ADB not found"):
            find_adb("missing-study-monitor-adb.exe")

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
