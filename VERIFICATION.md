# Verification — 28 October 2026

## Completed locally

- Used the existing `langchain` Python 3.12 environment with its installed Streamlit 1.50.0. No environment packages were changed.
- 21 offline unit checks passed: telemetry validation, both calibration positions, five-second collection, unstable/interrupted calibration, short glances, sustained turning, recovery, missing/multiple faces, settings/pause resets, timestamp gaps, run changes, stale/duplicate/out-of-order records, reader errors and dashboard backlog handling.
- Streamlit testing API: initial screen rendered without exceptions; missing ADB produced an actionable message; synthetic incoming measurements exercised studying, sustained-away and stale-data transitions without UI exceptions.
- Manual-label and JSON-export controls worked with synthetic measurements. These were software checks, not camera observations.
- Python syntax checks passed.
- Pinned ML Kit and CameraX dependencies were available from Google's Maven repository.
- Official Gradle 8.9 wrapper binary downloaded; SHA-256 matched the published checksum.

## Android build

The laptop has Java 8 on PATH. Android SDK, ADB and JDK 17 were not found in the inspected locations, so no local APK build or installation was performed. No SDK was installed automatically.

The repository includes a GitHub Actions workflow to run the Python checks, build/lint the Android app with JDK 17 and upload a debug APK. Its actual result will be recorded after the first run; the presence of a workflow is not itself evidence of a successful Android build.

## Still needs a physical Android phone

- Install APK and grant camera permission.
- Verify numeric telemetry is available through USB debugging on that phone.
- Check rotated input/head angles, face-size rejection and detection with glasses/poor lighting.
- Verify Start/Stop and background/foreground camera release.
- Test USB removal, authorization, reconnect and phone-app restart.
- Calibrate screen and notebook positions and measure real false reminders.
- Measure detector latency, battery impact and heating on a low-cost phone over a sustained session.

No real phone performance or attention-detection accuracy is claimed.
