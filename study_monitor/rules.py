"""Phone-facing head-position rules, not eye-gaze or attention detection."""

from dataclasses import asdict, dataclass, replace
from statistics import median

from .telemetry import Measurement, number

UNKNOWN = "Unknown"
FACING = "Facing phone screen"
LOOKING_AWAY = "Looking away"


def angle_delta(a, b):
    return (a - b + 180) % 360 - 180


@dataclass(frozen=True)
class Settings:
    yaw_tolerance: float = 20
    pitch_tolerance: float = 15
    away_seconds: float = 5
    recovery_seconds: float = 2
    smoothing_alpha: float = 0.3
    center_yaw: float = 0
    center_pitch: float = 0

    def __post_init__(self):
        for name, low, high in (("yaw_tolerance", 1, 90), ("pitch_tolerance", 1, 90),
                                ("away_seconds", 1, 30), ("recovery_seconds", 0.2, 10),
                                ("smoothing_alpha", 0.05, 1),
                                ("center_yaw", -180, 180), ("center_pitch", -180, 180)):
            number(getattr(self, name), name, low, high)


class RuleEngine:
    version = 2

    def __init__(self):
        self.settings = Settings()
        self.calibration = None
        self.reference_source = "default"
        self.calibration_message = "Using default front-facing angles. Calibration is optional."
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
        self.within_screen_range = None
        if self.calibration is not None:
            self.calibration.clear()

    def update_settings(self, settings):
        if settings != self.settings:
            self.settings = settings
            self.reset("Settings changed; decision timers reset.")

    def begin_calibration(self):
        self.calibration = []
        self.reset("Look directly at the phone and hold steadily for five seconds.")
        self.calibration_message = self.reason

    def cancel_calibration(self):
        self.calibration = None
        self.reset("Calibration cancelled.")
        self.calibration_message = self.reason

    def use_default_reference(self):
        self.calibration = None
        self.reference_source = "default"
        self.settings = replace(self.settings, center_yaw=0, center_pitch=0)
        self.reset("Using default front-facing angles; no calibration required.")
        self.calibration_message = self.reason

    def export_profile(self):
        return {"schema_version": 2, "settings": asdict(self.settings), "reference_source": self.reference_source}

    def load_profile(self, profile):
        if not isinstance(profile, dict) or type(profile.get("schema_version")) is not int or profile["schema_version"] != 2:
            raise ValueError("Expected a version 2 phone-screen settings file; older notebook profiles are not supported.")
        values = profile.get("settings")
        if not isinstance(values, dict) or set(values) != set(asdict(Settings())):
            raise ValueError("Settings file has missing or unsupported fields.")
        source = profile.get("reference_source")
        if source not in ("default", "captured"):
            raise ValueError("Unknown reference_source")
        settings = Settings(**values)
        self.settings = settings
        self.reference_source = source
        self.calibration = None
        self.reset("Testing saved phone-screen settings; decision timers reset.")
        self.calibration_message = "Using default front-facing angles." if source == "default" else "Using an optionally captured front-facing position."

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
            samples = self.calibration
            samples.append((now, measurement.yaw, measurement.pitch))
            duration = now - samples[0][0]
            self.reason = f"Capturing front-facing position: {min(duration, 5):.1f}/5 seconds."
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
                    self.settings = replace(self.settings, center_yaw=yaw, center_pitch=pitch)
                    self.reference_source = "captured"
                    self.calibration = None
                    self.reset("Front-facing position captured. Save settings to use it in Test mode.")
                    self.calibration_message = self.reason
            return True
        if self.smoothed is None:
            self.smoothed = (measurement.yaw, measurement.pitch)
        else:
            alpha = self.settings.smoothing_alpha
            self.smoothed = tuple(old + alpha * angle_delta(new, old)
                                  for old, new in zip(self.smoothed, (measurement.yaw, measurement.pitch)))
        yaw, pitch = self.smoothed
        self.within_screen_range = (abs(angle_delta(yaw, self.settings.center_yaw)) <= self.settings.yaw_tolerance
                                    and abs(angle_delta(pitch, self.settings.center_pitch)) <= self.settings.pitch_tolerance)
        candidate = FACING if self.within_screen_range else LOOKING_AWAY
        if candidate != self.candidate:
            self.candidate = candidate
            self.candidate_since = now
        self.elapsed = now - self.candidate_since
        threshold = self.settings.recovery_seconds if candidate == FACING else self.settings.away_seconds
        if self.elapsed >= threshold:
            self.status = candidate
        location = "Head facing the phone" if self.within_screen_range else "Head turned away from the phone"
        self.reason = f"{location} for {self.elapsed:.1f}s (threshold {threshold:g}s)."
        return True

    def snapshot(self):
        return {"status": self.status, "is_facing_screen": {FACING: True, LOOKING_AWAY: False}.get(self.status),
                "reason": self.reason, "elapsed_seconds": round(self.elapsed, 3),
                "candidate": self.candidate, "within_screen_range": self.within_screen_range,
                "smoothed_angles": self.smoothed, "reference_source": self.reference_source,
                "settings": asdict(self.settings)}
