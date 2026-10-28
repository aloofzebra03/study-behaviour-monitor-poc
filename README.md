# Study Behaviour Monitor — USB POC

Use your Android phone's camera to estimate whether your head is **facing the phone screen** or **looking away**. View the result and tune its settings on your laptop.

The model runs on the **phone**, not the laptop. Only numeric measurements travel over USB. The phone shows the camera preview; the laptop does not receive video.

~~~text
Phone camera → Google ML Kit → USB cable → local Streamlit dashboard
~~~

**Important:** this estimates head direction, not exact eye gaze, attention or learning. Facing the phone does not prove someone is reading it. There is no notebook position and calibration is optional.

## Before you start

You need:

- An **Android phone running Android 6.0 or newer**, preferably with a front camera. This APK does not work on iPhones.
- A laptop and a **USB cable that carries data**, not a charging-only cable.
- This project folder, Python and Google's small Platform Tools package.
- The POC's **app-debug.apk** file, installed once on each phone.
- Internet for the initial downloads. Once set up, this USB POC needs no API key, internet service, login or backend server.

The instructions below use **Windows PowerShell**. You do not need Android Studio, Java or an emulator if you use the already-built APK. macOS/Linux commands and optional Android build instructions are at the end.

The app was tested on a Samsung S25 Ultra. Its minimum Android version does not guarantee performance on every older/cheaper phone; test detection speed, lighting and heating on your own device.

## First-time setup — Windows

Do these steps once. Afterwards, use [Run it again](#run-it-again).

### 1. Get the code folder

If someone already gave you this folder, keep it and continue.

Otherwise, open the [GitHub repository](https://github.com/aloofzebra03/study-behaviour-monitor-poc), click **Code → Download ZIP**, and extract the ZIP. Cloning with Git is optional.

Open the extracted folder that contains **app.py** and **requirements.txt**. This is the **project folder**. All commands below run from here.

In File Explorer, right-click an empty space inside that folder and choose **Open in Terminal**. Use PowerShell. You can also open PowerShell and run the following, replacing the example path with your actual folder:

~~~powershell
cd "C:\path\to\your\project"
~~~

You do not need to edit any source code or create an .env file.

### 2. Set up Python

Install **Python 3.12** from [python.org](https://www.python.org/downloads/) if you do not already have it. On Windows, select **Add python.exe to PATH** during installation, then open a new terminal.

Check:

~~~powershell
python --version
~~~

The project needs Python 3.10 or newer and has been tested with Python 3.12. If Windows opens the Microsoft Store instead, install Python and check the installation/PATH before continuing.

Create a project-specific environment and install the dependency:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
~~~

There is no activation command to run, so PowerShell execution-policy changes are not needed.

**Already using the existing langchain environment?** You can skip creating .venv if Streamlit 1.50.0 is installed there. The equivalent run command is shown under Run it again.

### 3. Get the Android APK

You need **this project's app-debug.apk**, not the older base.apk.

If someone gave you the APK, copy it into the project folder, beside app.py. If your folder already has it under **android/app/build/outputs/apk/debug/app-debug.apk**, copy that file beside app.py for the commands below.

If you need to download it:

1. Open the repository's [Actions page](https://github.com/aloofzebra03/study-behaviour-monitor-poc/actions).
2. Sign in to GitHub. GitHub requires sign-in to download workflow artifacts; alternatively, ask the person sharing the POC to send you the APK directly.
3. Open a **successful, green** run of **Check rules and build Android APK**.
4. Find **Artifacts → study-monitor-debug-apk**.
5. Download and extract it, then put **app-debug.apk** beside app.py.

The artifact expires after 14 days. If it has expired, ask the repository owner to rerun the workflow or send a recent APK. You do not need to build Android yourself.

[GitHub's artifact-download instructions](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)

### 4. Get the USB tools

Download **SDK Platform-Tools for Windows** from [Google's Platform Tools page](https://developer.android.com/tools/releases/platform-tools) and extract the ZIP.

Inside the project folder, create a folder named **tools**. Put the extracted **platform-tools** folder inside it. Keep the whole package, including its DLL files; do not copy only adb.exe.

The folder should look like this:

~~~text
your-project/
    app.py
    requirements.txt
    app-debug.apk
    study_monitor/
    android/
    tools/
        platform-tools/
            adb.exe
            AdbWinApi.dll
            AdbWinUsbApi.dll
            ...other downloaded files
~~~

If tools/platform-tools/adb.exe already exists in the folder you were given, check it before downloading again:

~~~powershell
.\tools\platform-tools\adb.exe version
~~~

**Note:** downloaded code ZIPs/clones do not include .venv, Platform Tools or compiled APKs. Those are local setup files, not committed source code.

### 5. Enable the phone's settings

Menu names vary by brand and Android version. You can search the phone's Settings app for **Build number**, **Developer options** and **USB debugging**.

**Samsung Galaxy**

1. Open **Settings → About phone → Software information**.
2. Tap **Build number seven times**.
3. Enter your PIN/password if asked. A message should say developer mode is enabled.
4. Return to the main Settings screen and open **Developer options**, usually near the bottom.
5. Turn on **USB debugging** and confirm its prompt.

**Google Pixel / many other Android phones**

1. Open **Settings → About phone → Build number** and tap seven times.
2. Enter your PIN if asked.
3. Open **Settings → System → Developer options** and turn on **USB debugging**.

For other brands, the same settings may be under **About device**, **Software information** or **Additional settings**. Follow the device manufacturer's instructions if the menu differs. You do not need root access, bootloader unlocking or wireless debugging.

[Android's Developer options guide](https://developer.android.com/studio/debug/dev-options)

**Samsung Auto Blocker, only if it prevents debugging/installing**

If USB debugging is greyed out, or the phone explicitly says **Auto Blocker** is blocking USB commands or the APK, check **Settings → Security and privacy → Auto Blocker**. It is a protective feature. Only temporarily turn it off for this test if you trust the laptop and this APK, and restore it when finished. Do not disable unrelated protections or Play Protect.

[Samsung's Auto Blocker explanation](https://www.samsung.com/us/support/answer/ANS10003636/)

If a work/school-managed phone prohibits debugging or app installation, ask its administrator rather than trying to bypass the restriction.

### 6. Connect and authorize the laptop

1. Connect the phone with the data-capable USB cable.
2. Keep the phone **unlocked**.
3. If offered a USB mode, choose **File transfer / Android Auto**. This can help with detection, but it does not replace enabling USB debugging.
4. Accept **Allow USB debugging?** on the phone. Only approve a computer you trust. **Always allow from this computer** is optional for your own laptop.
5. In PowerShell, from the project folder, run:

~~~powershell
.\tools\platform-tools\adb.exe devices -l
~~~

Successful output looks like:

~~~text
List of devices attached
YOUR_PHONE_ID    device ...
~~~

- **device:** ready; continue.
- **unauthorized:** unlock the phone and accept its debugging prompt, then retry.
- **offline:** reconnect the cable and retry.
- **No phone listed:** check USB debugging, the cable, another USB port and the phone's USB mode. Windows may need the manufacturer's Android USB driver.

Seeing the phone in Windows File Explorer does not by itself mean USB debugging is ready. ADB must show **device**.

[Android USB setup and manufacturer-driver guidance](https://developer.android.com/studio/run/device)

### 7. Install and start the phone app

From the project folder:

~~~powershell
.\tools\platform-tools\adb.exe install -r .\app-debug.apk
~~~

Wait for **Success**. If the phone asks you to approve installation, review and approve this POC app yourself.

If more than one device is connected, explicitly choose the ID from the previous command:

~~~powershell
.\tools\platform-tools\adb.exe -s YOUR_PHONE_ID install -r .\app-debug.apk
~~~

On the phone:

1. Open **Study Monitor USB** from the app list.
2. Press **Start**.
3. Allow **Camera** access. **While using the app** is convenient; if you choose **Only this time**, you may need to approve it again later.
4. You should see your camera preview and face/angle information.
5. Keep this app **open in the foreground**. Switching to another phone app, locking the phone or pressing Stop stops capture.

If camera access was denied, open **Settings → Apps → Study Monitor USB → Permissions → Camera** and allow it while using the app.

**Connecting a cable does not automatically install or start the APK, enable debugging or grant camera permission.** Install once per phone; press Start each session.

### 8. Start the dashboard

In PowerShell, from the project folder:

~~~powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
~~~

Leave this terminal open. Open **http://localhost:8501** on the **laptop**, not on the phone.

In the left sidebar:

1. Click **Refresh devices**.
2. Select your phone. Its state should be **device**.
3. Click **Connect**.

The dashboard finds tools/platform-tools/adb.exe automatically. If you keep ADB elsewhere, expand **Advanced USB setup** and enter the full path to **adb.exe**, not just its folder.

## Test whether it works

Leave **Mode → Test** selected. No calibration is required.

1. Hold or prop the phone with its front camera near eye level.
2. Keep one face clearly visible and use reasonable lighting.
3. Face the phone for at least **two seconds**. Expect the large green **FACING THE SCREEN** result.
4. Turn your head moderately sideways, or sufficiently up/down, while keeping your face visible. Hold for about **six to seven seconds**: the default looking-away delay is five seconds, plus a little smoothing time. Expect **LOOKING AWAY**.
5. Face the phone again for two seconds to recover.
6. If your face disappears, multiple faces are detected or fresh data stops, expect **CANNOT ASSESS YET** rather than an automatic looking-away result.

A short glance can retain the previous result until the delay finishes. The progress bar shows a pending change. Open **Model measurements and rule details** if you want the raw values.

Turning completely away can make face detection fail. In that case **CANNOT ASSESS YET** is expected; the POC deliberately does not treat every missing face as looking away.

Your face must be large enough in the camera input (roughly 100×100 pixels or more). If it is too small, move the phone closer. The preview may be mirrored; the numeric angles follow the camera input, not the mirrored display.

The phone currently shows the camera app, not an integrated tutoring screen. This POC does not monitor you in the background while you use a different Android app.

## Tune the settings

Select **Tune / calibrate**. The controls are on the **left** and the large live result stays alongside them on the **right**.

| Control | Meaning | Default |
| --- | --- | --- |
| Allowed sideways turn | Larger values allow more left/right head movement | ±20° |
| Allowed up/down tilt | Larger values allow more vertical head movement | ±15° |
| Looking-away delay | How long to wait before confirming looking away | 5 seconds |
| Facing-screen delay | How long to wait before confirming a return | 2 seconds |
| Smoothing | Lower = steadier/slower; higher = faster/more sensitive to jitter | 0.3 |

Adjust one control at a time while watching the result. These values are starting points, not accuracy guarantees.

**Optional front-facing reference:** if the phone angle makes the default result unsuitable, open **Optional: capture a front-facing reference**, look directly at the phone and press **Capture front-facing position**. Hold steadily for five seconds. Movement or missing data makes collection restart. There is no notebook position. **Use default front-facing angles** removes this personal reference.

### Save, download and reuse someone's settings

- **Save settings and test:** saves the current settings for this browser session and switches to Test.
- **Download tuned settings (.json):** downloads the current edits, even before you press Save.
- **Download active settings (.json)** in Test: downloads the settings currently being tested.
- Save/download are disabled while reference capture is incomplete.
- Switching back to Test without Save discards unsaved edits.

To apply a file another person sent you:

1. In the sidebar, find **Import settings**.
2. Under **Load a tuned settings file (.json)**, choose the downloaded JSON.
3. If valid, it becomes active and is saved for Test in this browser session. Invalid files show an error without replacing your settings.

No source-code change, APK reinstall or model retraining is needed. Import updates this dashboard session, **not the repository's permanent defaults**. Download the file to keep it across browser-session resets.

A captured reference is specific to the person and camera position. Shared angle limits/delays can be useful, but verify them on the new setup. Older two-position calibration files are not supported.

Optional manual labels and recent-measurement exports are inside a Tune-mode expander. The dashboard retains at most 1,500 recent measurements in memory. No video is saved or sent to the laptop. Numeric measurements and personal reference angles are still personal data; share them deliberately.

## Run it again

After the one-time setup:

1. Connect USB, unlock the phone and approve debugging if asked.
2. Open **Study Monitor USB → Start**; approve camera access if asked.
3. From the project folder, run:

~~~powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
~~~

4. Open localhost:8501 and click **Refresh devices → select phone → Connect**.
5. Optionally import your saved JSON.

If you already use this project's installed Streamlit in the **langchain** environment instead of .venv:

~~~powershell
micromamba run -n langchain python -m streamlit run app.py --server.address 127.0.0.1
~~~

To finish: press **Stop on the phone**, click **Disconnect** in Streamlit, then press **Ctrl+C** in the laptop terminal to stop the dashboard. Disconnect alone does not stop the phone camera. Turn off USB debugging afterwards if no longer needed, and restore any protection you temporarily changed.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| python is not recognized | Install Python, enable its PATH option and open a new terminal. |
| app.py / requirements.txt not found | Open the folder that actually contains those files; a ZIP can have an extra nested directory. |
| ADB not found | Keep the full Platform Tools folder at tools/platform-tools, or enter its adb.exe path under Advanced USB setup. |
| adb.exe cannot start | Keep its accompanying DLLs; re-extract the official package if needed. |
| Phone appears in Explorer but not ADB | Enable USB debugging; check authorization, cable, USB mode and manufacturer driver. |
| unauthorized | Unlock the phone and approve the USB debugging prompt. |
| offline / disconnected | Reconnect USB, refresh devices and reconnect the dashboard. |
| More than one device/emulator | Use adb's -s YOUR_PHONE_ID option for installation; select that phone in Streamlit. |
| app-debug.apk is missing | Download/extract the GitHub build artifact and put the APK beside app.py. Source ZIPs do not contain it. |
| APK update incompatible | A different debug build may have a different signing key. Remove the previous POC app manually, then install the new one. This removes that app's local data. |
| APK installation blocked | Read the phone's message. Check the device's installation policy or Samsung Auto Blocker if specifically mentioned; do not disable unrelated protections. |
| Camera permission denied | Allow Camera for Study Monitor USB in Android Settings, then reopen the app and press Start. |
| Connected but no live data | Press Start in this project's phone app, keep it in the foreground and check camera permission. The old base.apk does not send this contract. |
| Cannot assess yet | Read the reason: waiting for the confirmation delay, missing/multiple/small faces or stale data. Calibration is optional, not a prerequisite. |
| Wrong facing/away result | Put the camera near eye level; inspect angles; tune tolerances or capture an optional front-facing reference. Eyes can move independently of the head. |
| Dashboard fell behind | Keep the laptop tab active; stale readings are discarded and timers reset. |
| Old-looking UI or import error after pulling updates | Stop this dashboard's terminal with Ctrl+C, run the launch command again, then refresh the page. |
| Port 8501 is already in use | Stop your previous dashboard, or add --server.port 8502 to the launch command and open localhost:8502. |
| Imported settings disappear later | They are session-local. Keep the JSON file and import it again. |
| Phone becomes hot or detection is slow | Stop the test and let it cool. Check lighting and background load; this POC still needs performance verification on low-cost phones. |

To check the phone's numeric output separately:

~~~powershell
.\tools\platform-tools\adb.exe logcat -v raw "StudyMonitor:I" "*:S"
~~~

Press Ctrl+C to stop that log viewer. The POC reads only this dedicated tag; it does not clear the phone's logs or stop a shared ADB server.

## macOS / Linux notes

Use the matching Google Platform Tools download and put its whole platform-tools folder inside tools. There is no adb.exe on these systems; the executable is named **adb**. Linux may need USB device permissions; see the [official device setup guide](https://developer.android.com/studio/run/device).

From the project folder, after putting app-debug.apk beside app.py:

~~~sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./tools/platform-tools/adb devices -l
./tools/platform-tools/adb install -r ./app-debug.apk
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
~~~

The app has been exercised on Windows; the macOS/Linux commands are provided as setup guidance, not a claim of hardware testing there.

## Optional: build the Android APK yourself

Skip this section if you have a built APK.

Open **android/** as a project in Android Studio. Use **JDK 17**, **Android SDK Platform 35** and **Build Tools 34.0.0**. Let Gradle sync. No separate Gradle install is needed; the project includes a wrapper.

On Windows:

~~~powershell
cd android
.\gradlew.bat assembleDebug
~~~

Output: **android/app/build/outputs/apk/debug/app-debug.apk**, relative to the project folder. Return to the project folder and copy it beside app.py if following the installation command above. Use a drive with enough free space for the SDK and build caches; no emulator is required.

## What each code file does

| File/folder | Purpose |
| --- | --- |
| android/ | Phone app: camera preview, bundled ML Kit and numeric telemetry |
| app.py | Test/Tune UI, USB controls, settings download/import |
| study_monitor/telemetry.py | Validates messages from Android |
| study_monitor/usb.py | Reads the USB log stream and rejects old/invalid data |
| study_monitor/rules.py | Head-angle thresholds, optional reference capture and timing |
| tests/ | Offline checks that do not require a phone |

Run the offline checks from the project folder:

~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
~~~

See **VERIFICATION.md** for what was actually checked and what still needs manual testing.

## Streamlit Cloud and next steps

**This version must run on the laptop connected to the phone.** Deploying it to Streamlit Cloud does not give that remote server access to the viewer's USB ports, install the APK or grant phone permissions.

For now, share the folder/ZIP, APK and any tuned settings JSON, and have each tester run the dashboard locally.

Future remote use would need a small FastAPI receiver: either the phone sends numeric measurements directly over the internet, or a local USB helper forwards them. Browser WebUSB/ADB is another possible direction but needs additional browser-specific development. None of these remote options is implemented in this USB POC.
