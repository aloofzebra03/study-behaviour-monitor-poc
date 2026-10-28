# Verification — 28 October 2026

## Completed locally

- Used the existing `langchain` Python 3.12 environment with its installed Streamlit 1.50.0. No environment packages were changed.
- 24 current offline unit checks passed: telemetry validation, default phone-facing reference without calibration, optional five-second capture, unstable/interrupted capture, short glances, sustained turning, recovery, missing/multiple faces, settings resets, timestamp gaps, run changes, stale/duplicate/out-of-order records, reader errors, invalid ADB paths, backlog handling and settings-profile validation/round trips.
- Streamlit testing API: initial screen rendered without exceptions; missing ADB produced an actionable message; synthetic incoming measurements exercised studying, sustained-away and stale-data transitions without UI exceptions.
- Manual-label and JSON-export controls worked with synthetic measurements. These were software checks, not camera observations.
- Current two-mode UI: Test starts without sliders or calibration buttons; Tune exposes five tuning sliders and optional reference capture. Save switches back to Test with the edited settings. Unsaved changes are discarded when returning to Test. Switching modes cancels an in-progress capture. These interactions passed Streamlit testing-API checks without exceptions.
- Latest UI redesign: Test renders a large color-coded HTML status card, Tune places controls and results in separate adjacent Streamlit columns, and settings download is directly visible. Layout structure and Save-to-Test behaviour passed Streamlit testing-API checks. Static CSS and escaped dynamic reason text are used; no generated HTML is accepted from a model.
- Download payload checks confirmed Tune downloads contain current unsaved edits, Test downloads match saved settings, and completing optional reference capture refreshes the downloaded reference angles and re-enables Save/Download. No personal reference was used for these synthetic checks.
- Desktop visual verification was attempted using the computer-use/browser helper, but the runtime repeatedly exited before initialization (`CreateProcessWithLogonW failed: 267`). No screenshot-based verification is claimed. The functional UI checks above did run.
- Python syntax checks passed.
- A temporary loopback-only Streamlit process returned HTTP 200 and a healthy `/_stcore/health`; that process was stopped afterwards.
- Pinned ML Kit and CameraX dependencies were available from Google's Maven repository.
- Official Gradle 8.9 wrapper binary downloaded; SHA-256 matched the published checksum.
- Google's standalone Windows Platform Tools were downloaded into ignored `tools/platform-tools`; no PATH or Python environment change was made. ADB 37.0.1 starts successfully and is auto-discovered by the dashboard.

## Android build

The laptop has Java 8 on PATH. Android SDK and JDK 17 were not found in the inspected locations, so no local APK build was performed. No SDK was installed locally.

The GitHub Actions [build run 40631499269](https://github.com/aloofzebra03/study-behaviour-monitor-poc/actions/runs/40631499269) **passed**: Python checks, Android `assembleDebug`, Android `lintDebug` and debug APK upload. It used JDK 17 and the pinned Gradle/Android dependencies. Earlier setup failures were fixed by explicitly preparing SDK tools and excluding Google's obsolete `tools` package.

The built APK was downloaded to ignored `android/app/build/outputs/apk/debug/app-debug.apk` (42,424,454 bytes). Its SHA-256 is `7a73ed9173f3e425f609483815b382323cdc5c85861e1f4f811b86665ae3e384`. The APK contains ARM64, ARMv7, x86 and x86-64 native libraries. Its artifact download checksum was also verified against GitHub's digest.

The subsequent two-mode change is Python-only; the installed APK's numeric contract remains compatible. Its startup hint about calibrating positions belongs to the earlier dashboard; the new Test mode does not require calibration.

## Physical-phone observations

- After the user enabled USB debugging, ADB detected an authorized Samsung S25 Ultra (SM-S938B), Android 17.
- Installed the built APK successfully and launched the activity. Camera permission was not granted automatically.
- Later inspected this app's dedicated log buffer: 313 successful detector results, followed by `app_backgrounded`. This confirms ML Kit ran on the phone; it is not a ground-truth accuracy test.
- A subsequent five-second check using the actual Python USB reader connected successfully but received zero fresh measurements while capture was inactive. The result stayed Unknown. No camera was started or permission changed by that check.

## Still needs manual phone verification

- Start the phone app again and verify the live dashboard receives fresh measurements continuously.
- Check rotated input/head angles, face-size rejection and detection with glasses/poor lighting.
- Verify Start/Stop and background/foreground camera release.
- Test USB removal, authorization, reconnect and phone-app restart.
- Compare human-observed facing/away behaviour against predictions in default Test mode and with tuned settings. Check optional front-facing reference capture.
- Measure detector latency, battery impact and heating on a low-cost phone over a sustained session.

No real phone performance or attention-detection accuracy is claimed.
