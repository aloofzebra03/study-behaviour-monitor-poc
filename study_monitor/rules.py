"""Calibrated study-posture rules. These do not measure learning or eye gaze."""

from dataclasses import asdict, dataclass
from statistics import median

from .telemetry import Measurement, number

NORMAL = "Normal study posture"
AWAY = "Possibly away from work"
UNKNOWN = "Cannot assess"
PAUSED = "Taking a break"
POSITIONS = ("reading", "writing")
SIDES = ("left", "front", "right")
HEIGHTS = ("above", "level", "below")


def angle_delta(a, b):
    return (a - b + 180) % 360 - 180


def median_angle(values):
    anchor = values[0]
    return angle_delta(anchor + median([angle_delta(value, anchor) for value in values]), 0)


@dataclass(frozen=True)
class Settings:
    yaw_tolerance: float = 20
    pitch_tolerance: float = 15
    away_seconds: float = 10
    recovery_seconds: float = 2
    smoothing_alpha: float = 0.3

    def __post_init__(self):
        for name, low, high in (("yaw_tolerance", 1, 90), ("pitch_tolerance", 1, 90),
                                ("away_seconds", 1, 60), ("recovery_seconds", 0.2, 10),
                                ("smoothing_alpha", 0.05, 1)):
            number(getattr(self, name), name, low, high)


class RuleEngine:
    version = 3

    def __init__(self):
        self.settings = Settings()
        self.study_positions = {}
        self.placement = {"side": "front", "height": "level"}
        self.calibration = None
        self.calibration_message = "Capture normal reading and writing for this fixed camera placement."
        self.last_identity = None
        self.last_capture_ms = None
        self.paused = False
        self.reset("Set up reading and writing positions before monitoring.")

    @property
    def ready(self):
        return set(self.study_positions) == set(POSITIONS)

    def reset(self, reason):
        self.status = PAUSED if self.paused else UNKNOWN
        self.reason = "Taking a break. Resume whenever you are ready." if self.paused else reason
        self.candidate = None
        self.candidate_since = None
        self.elapsed = 0.0
        self.smoothed = None
        self.matched_position = None
        if self.calibration is not None:
            self.calibration["samples"].clear()
            self.calibration_message = reason

    def update_settings(self, settings):
        if settings != self.settings:
            self.settings = settings
            self.reset("Tuning changed; observation timers reset.")

    def set_paused(self, paused):
        if type(paused) is not bool:
            raise ValueError("Break state must be true or false.")
        self.paused = paused
        self.calibration = None
        self.reset("Break finished; waiting for a fresh continuous observation.")

    def clear_positions(self, reason="Camera or seating changed. Capture reading and writing again."):
        self.study_positions.clear()
        self.calibration = None
        self.reset(reason)
        self.calibration_message = reason

    def set_placement(self, side, height):
        if side not in SIDES or height not in HEIGHTS:
            raise ValueError("Unknown camera placement.")
        placement = {"side": side, "height": height}
        if placement != self.placement:
            self.placement = placement
            self.clear_positions()
            return True
        return False

    def begin_calibration(self, position):
        if position not in POSITIONS:
            raise ValueError("Choose reading or writing.")
        if self.paused:
            raise ValueError("Resume monitoring before capturing a study position.")
        # An unsuccessful replacement must not leave the old reference usable.
        self.study_positions.pop(position, None)
        self.calibration = {"position": position, "samples": []}
        self.reset(f"{position.capitalize()} setup: do your usual {position} for five seconds.")
        self.calibration_message = self.reason

    def cancel_calibration(self):
        self.calibration = None
        self.reset("Position capture cancelled.")
        self.calibration_message = self.reason

    def export_profile(self):
        return {"schema_version": 3, "settings": asdict(self.settings),
                "study_positions": {name: dict(point) for name, point in self.study_positions.items()},
                "placement": dict(self.placement)}

    def load_profile(self, profile, reuse_positions=False):
        """Old phone-facing exports supply thresholds only, never study references."""
        if type(reuse_positions) is not bool or not isinstance(profile, dict):
            raise ValueError("Expected a study settings JSON object.")
        version = profile.get("schema_version")
        if type(version) is not int or version not in (2, 3):
            raise ValueError("Expected version 3 study settings or version 2 phone-facing thresholds.")
        values = profile.get("settings")
        if not isinstance(values, dict):
            raise ValueError("Missing settings.")
        allowed = set(asdict(Settings()))
        if version == 2:
            if set(values) != allowed | {"center_yaw", "center_pitch"}:
                raise ValueError("Invalid older phone-facing settings.")
            number(values["center_yaw"], "center_yaw", -180, 180)
            number(values["center_pitch"], "center_pitch", -180, 180)
            if profile.get("reference_source") not in ("default", "captured"):
                raise ValueError("Invalid older reference_source.")
            positions = {}
            placement = dict(self.placement)
        else:
            if set(values) != allowed:
                raise ValueError("Missing or unsupported settings fields.")
            raw_positions = profile.get("study_positions")
            placement = profile.get("placement")
            if not isinstance(raw_positions, dict) or not set(raw_positions) <= set(POSITIONS):
                raise ValueError("Only reading and writing study references are supported.")
            positions = {}
            for name, point in raw_positions.items():
                if not isinstance(point, dict) or set(point) != {"yaw", "pitch"}:
                    raise ValueError(f"Invalid {name} reference.")
                positions[name] = {axis: float(number(point[axis], axis, -180, 180)) for axis in ("yaw", "pitch")}
            if (not isinstance(placement, dict) or set(placement) != {"side", "height"}
                    or placement["side"] not in SIDES or placement["height"] not in HEIGHTS):
                raise ValueError("Invalid placement metadata.")
        settings = Settings(**{key: values[key] for key in allowed})
        # Validate the entire file before changing live state.
        self.settings = settings
        self.study_positions = positions if reuse_positions else {}
        if reuse_positions and version == 3:
            self.placement = dict(placement)
        self.calibration = None
        reason = ("Saved study setup loaded for the confirmed same placement." if self.ready
                  else "Thresholds loaded. Capture reading and writing for this camera placement.")
        self.reset(reason)
        self.calibration_message = reason

    def process(self, measurement: Measurement):
        identity = (measurement.run_id, measurement.sequence)
        if self.last_identity and measurement.run_id == self.last_identity[0]:
            if measurement.sequence <= self.last_identity[1]:
                return False
        if self.last_identity and measurement.run_id != self.last_identity[0]:
            self.reset("Phone app restarted; timers reset. Redo setup if the camera moved.")
            self.last_capture_ms = None
        if self.last_capture_ms is not None:
            gap = (measurement.capture_ms - self.last_capture_ms) / 1000
            if gap <= 0 or gap > 1:
                self.reset("Measurement gap; observation timers reset.")
        self.last_identity = identity
        self.last_capture_ms = measurement.capture_ms
        if self.paused:
            self.reset("Taking a break.")
            return True
        if not measurement.usable:
            errors = {
                "face_too_small_or_out_of_frame": "Face too small or out of frame. Adjust the camera so it sees reading and writing.",
                "monitoring_stopped": "Phone camera stopped. Press Start on the phone when ready.",
                "app_backgrounded": "Phone app is in the background; keep it open to monitor.",
                "detector_error": "Face detector unavailable. Check camera permission and restart capture.",
            }
            reason = (errors.get(measurement.error, measurement.error) if measurement.error else
                      "No face visible. Adjust the camera; this is not evidence of distraction." if measurement.face_count == 0 else
                      "Multiple faces visible; cannot assess one student." if measurement.face_count else "Measurements unavailable.")
            self.reset(reason)
            return True
        now = measurement.capture_ms / 1000
        if self.calibration is not None:
            samples = self.calibration["samples"]
            samples.append((now, measurement.yaw, measurement.pitch))
            # Capture timestamps have millisecond precision; avoid 4.999999s at 5s.
            duration = round(now - samples[0][0], 3)
            position = self.calibration["position"]
            self.reason = f"Learning {position} position: {min(duration, 5):.1f}/5 seconds."
            self.calibration_message = self.reason
            if duration >= 5 and len(samples) >= 15:
                yaw = median_angle([s[1] for s in samples])
                pitch = median_angle([s[2] for s in samples])
                stable_count = sum(abs(angle_delta(s[1], yaw)) <= 15 and
                                   abs(angle_delta(s[2], pitch)) <= 15 for s in samples)
                if stable_count / len(samples) < 0.9:
                    samples.clear()
                    self.calibration_message = "Too much head movement. Continue your usual posture steadily; retrying."
                    self.reason = self.calibration_message
                else:
                    self.study_positions[position] = {"yaw": yaw, "pitch": pitch}
                    self.calibration = None
                    self.reset(f"{position.capitalize()} reference captured.")
                    self.calibration_message = self.reason
            return True
        if not self.ready:
            missing = ", ".join(name for name in POSITIONS if name not in self.study_positions)
            self.reset(f"Setup needed: capture {missing} for this camera placement.")
            return True
        if self.smoothed is None:
            self.smoothed = (measurement.yaw, measurement.pitch)
        else:
            alpha = self.settings.smoothing_alpha
            self.smoothed = tuple(old + alpha * angle_delta(new, old)
                                  for old, new in zip(self.smoothed, (measurement.yaw, measurement.pitch)))
        yaw, pitch = self.smoothed
        self.matched_position = next((name for name, point in self.study_positions.items()
            if abs(angle_delta(yaw, point["yaw"])) <= self.settings.yaw_tolerance
            and abs(angle_delta(pitch, point["pitch"])) <= self.settings.pitch_tolerance), None)
        candidate = NORMAL if self.matched_position else AWAY
        if candidate != self.candidate:
            self.candidate = candidate
            self.candidate_since = now
        self.elapsed = round(now - self.candidate_since, 3)
        threshold = self.settings.recovery_seconds if candidate == NORMAL else self.settings.away_seconds
        if self.elapsed >= threshold:
            self.status = candidate
        observation = (f"Matches the {self.matched_position} reference" if self.matched_position
                       else "Outside both usual study-position ranges")
        self.reason = f"{observation} for {self.elapsed:.1f}s (confirmation {threshold:g}s)."
        return True

    def snapshot(self):
        return {"status": self.status, "is_in_study_position": {NORMAL: True, AWAY: False}.get(self.status),
                "reason": self.reason, "setup_complete": self.ready, "paused": self.paused,
                "candidate": self.candidate, "matched_position": self.matched_position,
                "elapsed_seconds": round(self.elapsed, 3), "smoothed_angles": self.smoothed,
                "study_positions": {name: dict(point) for name, point in self.study_positions.items()},
                "placement": dict(self.placement), "settings": asdict(self.settings)}
