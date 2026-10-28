"""Pure rules: head position is an observable proxy, never proof of studying."""

from dataclasses import asdict, dataclass
from statistics import median

from .telemetry import Measurement

UNKNOWN = "Unknown"
STUDYING = "Likely studying"
OFF_TASK = "Possibly off-task"


def angle_delta(a, b):
    return (a - b + 180) % 360 - 180


@dataclass(frozen=True)
class Settings:
    yaw_tolerance: float = 20
    pitch_tolerance: float = 15
    away_seconds: float = 5
    recovery_seconds: float = 2
    smoothing_alpha: float = 0.3

    def __post_init__(self):
        for name, low, high in (("yaw_tolerance", 1, 90), ("pitch_tolerance", 1, 90),
                                ("away_seconds", 1, 30), ("recovery_seconds", 0.2, 10),
                                ("smoothing_alpha", 0.05, 1)):
            value = getattr(self, name)
            if not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}")


class RuleEngine:
    def __init__(self):
        self.settings = Settings()
        self.profiles = {}
        self.calibration = None
        self.calibration_message = "Calibrate both screen and notebook positions."
        self.last_identity = None
        self.last_capture_ms = None
        self.reset("Waiting for fresh phone measurements.")

    def reset(self, reason):
        self.status = UNKNOWN
        self.reason = reason
        self.candidate = None
        self.candidate_since = None
        self.elapsed = 0.0
        self.smoothed = None
        self.matched_position = None
        if self.calibration is not None:
            self.calibration["samples"].clear()

    def update_settings(self, settings):
        if settings != self.settings:
            self.settings = settings
            self.reset("Settings changed; decision timers reset.")

    def begin_calibration(self, position):
        if position not in ("screen", "notebook"):
            raise ValueError("Unknown calibration position")
        self.calibration = {"position": position, "samples": []}
        self.reset(f"Calibrating {position}; hold the position for five seconds.")
        self.calibration_message = self.reason

    def cancel_calibration(self):
        self.calibration = None
        self.reset("Calibration cancelled.")
        self.calibration_message = self.reason

    def clear_calibration(self):
        self.profiles.clear()
        self.calibration = None
        self.reset("Calibration cleared. Calibrate both positions.")
        self.calibration_message = self.reason

    def process(self, measurement: Measurement):
        identity = (measurement.run_id, measurement.sequence)
        if self.last_identity and measurement.run_id == self.last_identity[0]:
            if measurement.sequence <= self.last_identity[1]:
                return False
        if self.last_identity and measurement.run_id != self.last_identity[0]:
            self.reset("Phone monitoring restarted; timers reset.")
            self.last_capture_ms = None
        if self.last_capture_ms is not None:
            gap = (measurement.capture_ms - self.last_capture_ms) / 1000
            if gap <= 0 or gap > 1:
                self.reset("Measurement gap; waiting for a new continuous observation.")
                # Clock discontinuities cannot contribute to an existing candidate.
        self.last_identity = identity
        self.last_capture_ms = measurement.capture_ms
        if not measurement.usable:
            reasons = {0: "No face detected.", None: "Measurements unavailable."}
            self.reset(measurement.error or reasons.get(measurement.face_count, "Multiple faces detected."))
            return True
        now = measurement.capture_ms / 1000
        if self.calibration is not None:
            samples = self.calibration["samples"]
            samples.append((now, measurement.yaw, measurement.pitch))
            duration = now - samples[0][0]
            self.reason = f"Calibrating {self.calibration['position']}: {min(duration, 5):.1f}/5 seconds."
            self.calibration_message = self.reason
            if duration >= 5 and len(samples) >= 15:
                yaw = median(s[1] for s in samples)
                pitch = median(s[2] for s in samples)
                stable = all(abs(angle_delta(s[1], yaw)) <= 10 and
                             abs(angle_delta(s[2], pitch)) <= 10 for s in samples)
                if not stable:
                    samples.clear()
                    self.calibration_message = "Too much movement. Hold your normal position steadily; retrying."
                    self.reason = self.calibration_message
                else:
                    position = self.calibration["position"]
                    self.profiles[position] = {"yaw": yaw, "pitch": pitch}
                    self.calibration = None
                    self.reset(f"Saved {position} calibration.")
                    self.calibration_message = self.reason
            return True
        if len(self.profiles) != 2:
            self.reset("Calibrate both screen and notebook positions before assessment.")
            return True
        if self.smoothed is None:
            self.smoothed = (measurement.yaw, measurement.pitch)
        else:
            alpha = self.settings.smoothing_alpha
            self.smoothed = tuple(old + alpha * angle_delta(new, old)
                                  for old, new in zip(self.smoothed, (measurement.yaw, measurement.pitch)))
        yaw, pitch = self.smoothed
        self.matched_position = next((name for name, p in self.profiles.items()
                                     if abs(angle_delta(yaw, p["yaw"])) <= self.settings.yaw_tolerance
                                     and abs(angle_delta(pitch, p["pitch"])) <= self.settings.pitch_tolerance), None)
        candidate = STUDYING if self.matched_position else OFF_TASK
        if candidate != self.candidate:
            self.candidate = candidate
            self.candidate_since = now
        self.elapsed = now - self.candidate_since
        threshold = self.settings.recovery_seconds if candidate == STUDYING else self.settings.away_seconds
        if self.elapsed >= threshold:
            self.status = candidate
        location = f"Inside {self.matched_position} range" if self.matched_position else "Outside both calibrated ranges"
        self.reason = f"{location} for {self.elapsed:.1f}s (threshold {threshold:g}s)."
        return True

    def snapshot(self):
        return {"status": self.status, "is_studying": {STUDYING: True, OFF_TASK: False}.get(self.status),
                "reason": self.reason, "elapsed_seconds": round(self.elapsed, 3),
                "candidate": self.candidate, "matched_position": self.matched_position,
                "smoothed_angles": self.smoothed, "calibration": dict(self.profiles),
                "settings": asdict(self.settings)}
