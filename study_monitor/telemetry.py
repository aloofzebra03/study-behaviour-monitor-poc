"""Small, versioned contract shared with the independent Android app."""

import json
import math
from dataclasses import asdict, dataclass


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite and between {low} and {high}")
    return value


@dataclass(frozen=True)
class Measurement:
    run_id: str
    sequence: int
    capture_ms: int
    face_count: int | None
    yaw: float | None
    pitch: float | None
    roll: float | None
    bounds: tuple[float, float, float, float] | None
    error: str | None = None
    inference_ms: float | None = None
    schema_version: int = 1

    @property
    def usable(self):
        return self.error is None and self.face_count == 1

    def as_dict(self):
        return asdict(self)


def parse_measurement(line: str) -> Measurement:
    """Reject malformed measurements rather than silently treating null as zero."""
    if len(line) > 4096:
        raise ValueError("Telemetry line is too long")
    obj = json.loads(line)
    if not isinstance(obj, dict) or type(obj.get("schema_version")) is not int or obj["schema_version"] != 1:
        raise ValueError("Expected a schema_version=1 telemetry object")
    run_id = obj.get("run_id")
    if not isinstance(run_id, str) or not 1 <= len(run_id) <= 80:
        raise ValueError("Missing or invalid run_id")
    for name in ("sequence", "capture_ms"):
        if type(obj.get(name)) is not int or obj[name] < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    count = obj.get("face_count")
    if count is not None and (type(count) is not int or not 0 <= count <= 100):
        raise ValueError("Invalid face_count")
    error = obj.get("error")
    if error is not None and (not isinstance(error, str) or not 1 <= len(error) <= 120):
        raise ValueError("Invalid error")
    if count is None and not error:
        raise ValueError("Unavailable face count requires an error reason")
    angles = []
    for name in ("yaw", "pitch", "roll"):
        value = obj.get(name)
        angles.append(None if value is None else float(number(value, name, -180, 180)))
    bounds = obj.get("bounds")
    if bounds is not None:
        if not isinstance(bounds, list) or len(bounds) != 4:
            raise ValueError("bounds must contain left, top, right, bottom")
        bounds = tuple(float(number(v, "bounds", 0, 1)) for v in bounds)
        if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
            raise ValueError("Invalid face bounds")
    if count == 1 and not error and (None in angles or bounds is None):
        raise ValueError("A usable single face requires all angles and bounds")
    if count != 1 and (any(a is not None for a in angles) or bounds is not None):
        raise ValueError("Do not attach a person's measurements to an ambiguous face count")
    latency = obj.get("inference_ms")
    if latency is not None:
        latency = float(number(latency, "inference_ms", 0, 60000))
    return Measurement(run_id, obj["sequence"], obj["capture_ms"], count,
                       *angles, bounds, error, latency)
