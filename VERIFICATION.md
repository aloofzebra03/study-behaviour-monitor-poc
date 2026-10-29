# Verification — 29 October 2026

## Current reading/writing workflow: completed locally

- Used the existing langchain Python 3.12 environment and installed Streamlit 1.50.0. No environment packages were changed.
- All **34 offline unit checks passed**. Coverage includes telemetry validation; required reading/writing setup; accepting either posture; synthetic left/right/front and elevated camera-reference angles; brief glances; sustained departures and recovery; missing/multiple faces; breaks; unstable/interrupted captures; timestamp gaps; duplicate/out-of-order data; stale USB buffers; reader shutdown; settings validation and safe import.
- Synthetic placement checks exercise relative-angle logic only. They do not establish real camera detection accuracy from those positions.
- Captures complete at an exact five-second boundary even when recording starts at a fractional second. A regression check covers the floating-point boundary.
- Streamlit testing-API checks passed: initial Test requests setup; controls and large result occupy adjacent Tune columns; Save is disabled until both positions exist; placement metadata can change; Save switches to Test with both references; break/resume works; Phone moved clears live and saved references; switching modes cannot restore an invalidated setup.
- A one-off UI check exercised the actual reading and writing capture buttons with synthetic measurement batches. Both asynchronous completions refreshed download payloads; Save became enabled; Test download matched the saved setup.
- Profile checks confirmed thresholds-only import is the default; reference reuse is explicit; old version 2 phone-facing files never supply study references; invalid imports do not partially overwrite settings.
- Python syntax checks passed.
- The updated loopback-only Streamlit dashboard returned HTTP 200 and `ok` from its health endpoint on port 8501.
- Screenshot-based visual verification is not claimed. Earlier desktop/browser helper attempts failed before initialization. Functional Streamlit checks above are not a substitute for viewing the dashboard on different screen sizes.
- ADB starts successfully, but **no phone was connected** during these new reading/writing checks.
- No Android code changed for this workflow. The existing APK sends the same measurements and does not need reinstalling.

## Android build

The laptop has Java 8 on PATH. Android SDK and JDK 17 were not found in the inspected locations, so no local APK build was performed. No SDK was installed locally.

The GitHub Actions [build run 40631499269](https://github.com/aloofzebra03/study-behaviour-monitor-poc/actions/runs/40631499269) **passed**: Python checks, Android `assembleDebug`, Android `lintDebug` and debug APK upload. It used JDK 17 and the pinned Gradle/Android dependencies. Earlier setup failures were fixed by explicitly preparing SDK tools and excluding Google's obsolete `tools` package.

The built APK was downloaded to ignored `android/app/build/outputs/apk/debug/app-debug.apk` (42,424,454 bytes). Its SHA-256 is `7a73ed9173f3e425f609483815b382323cdc5c85861e1f4f811b86665ae3e384`. The APK contains ARM64, ARMv7, x86 and x86-64 native libraries. Its artifact download checksum was also verified against GitHub's digest.

The dashboard changes are Python-only; the installed APK's numeric contract remains compatible. The current dashboard requires reading and writing captures before assessment.

## Physical-phone observations

- After the user enabled USB debugging, ADB detected an authorized Samsung S25 Ultra (SM-S938B), Android 17.
- Installed the built APK successfully and launched the activity. Camera permission was not granted automatically.
- Later inspected this app's dedicated log buffer: 313 successful detector results, followed by `app_backgrounded`. This confirms ML Kit ran on the phone; it is not a ground-truth accuracy test.
- A subsequent five-second check using the actual Python USB reader connected successfully but received zero fresh measurements while capture was inactive. The result stayed Unknown. No camera was started or permission changed by that check.

## Still needs manual phone verification

- Connect a phone, start its camera and verify continuous fresh data in the new dashboard.
- Capture actual book-reading and writing positions, then compare human observations against the relative-posture result.
- Try a fixed phone on the left, right and front at practical heights. Verify the face remains detectable in both activities. Extreme side/overhead views may be unsuitable.
- Check brief glances, sustained departures, normal page scanning, returning to work, breaks and missing/multiple faces.
- Move the phone/book/seating, use Phone moved / redo setup and verify recapture.
- Check capture stability, rotated input, face size, glasses and poor lighting.
- Verify phone Start/Stop, foreground/background camera release, USB removal/reconnect and app restart.
- Measure latency, battery impact and sustained heating on a low-cost phone.

No actual attention/learning measurement or physical placement accuracy is claimed. Historical Samsung detector observations above confirm model execution, not validation of the new study-posture rules.
