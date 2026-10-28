# Verification — 28 October 2026

## Completed locally

- Used the existing `langchain` Python 3.12 environment with its installed Streamlit 1.50.0. No environment packages were changed.
- 22 offline unit checks passed: telemetry validation, both calibration positions, five-second collection, unstable/interrupted calibration, short glances, sustained turning, recovery, missing/multiple faces, settings/pause resets, timestamp gaps, run changes, stale/duplicate/out-of-order records, reader errors, invalid ADB paths and dashboard backlog handling.
- Streamlit testing API: initial screen rendered without exceptions; missing ADB produced an actionable message; synthetic incoming measurements exercised studying, sustained-away and stale-data transitions without UI exceptions.
- Manual-label and JSON-export controls worked with synthetic measurements. These were software checks, not camera observations.
- Python syntax checks passed.
- A temporary loopback-only Streamlit process returned HTTP 200 and a healthy `/_stcore/health`; that process was stopped afterwards.
- Pinned ML Kit and CameraX dependencies were available from Google's Maven repository.
- Official Gradle 8.9 wrapper binary downloaded; SHA-256 matched the published checksum.
- Google's standalone Windows Platform Tools were downloaded into ignored `tools/platform-tools`; no PATH or Python environment change was made. ADB 37.0.1 starts successfully and is auto-discovered by the dashboard. `adb devices -l` returned no connected devices.

## Android build

The laptop has Java 8 on PATH. Android SDK and JDK 17 were not found in the inspected locations, so no local APK build or phone installation was performed. No SDK was installed locally.

The GitHub Actions [build run 40631499269](https://github.com/aloofzebra03/study-behaviour-monitor-poc/actions/runs/40631499269) **passed**: Python checks, Android `assembleDebug`, Android `lintDebug` and debug APK upload. It used JDK 17 and the pinned Gradle/Android dependencies. Earlier setup failures were fixed by explicitly preparing SDK tools and excluding Google's obsolete `tools` package.

The built APK was downloaded to ignored `android/app/build/outputs/apk/debug/app-debug.apk` (42,424,454 bytes). Its SHA-256 is `7a73ed9173f3e425f609483815b382323cdc5c85861e1f4f811b86665ae3e384`. The APK contains ARM64, ARMv7, x86 and x86-64 native libraries. Its artifact download checksum was also verified against GitHub's digest.

This proves the app builds and passes static Android lint, not that the camera/model/USB path has been tested on a real phone.

## Still needs a physical Android phone

- Install APK and grant camera permission.
- Verify numeric telemetry is available through USB debugging on that phone.
- Check rotated input/head angles, face-size rejection and detection with glasses/poor lighting.
- Verify Start/Stop and background/foreground camera release.
- Test USB removal, authorization, reconnect and phone-app restart.
- Calibrate screen and notebook positions and measure real false reminders.
- Measure detector latency, battery impact and heating on a low-cost phone over a sustained session.

No real phone performance or attention-detection accuracy is claimed.
