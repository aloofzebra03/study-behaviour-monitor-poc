"""Run with: python -m streamlit run app.py"""

import json
import logging
import time
from collections import deque
from datetime import datetime, timezone

import streamlit as st

from study_monitor.rules import OFF_TASK, STUDYING, UNKNOWN, RuleEngine, Settings
from study_monitor.usb import UsbReader, find_adb, list_devices

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOG = logging.getLogger("study_dashboard")
st.set_page_config(page_title="Study position monitor", layout="wide")
st.title("Study position monitor · USB POC")
st.caption("ML Kit runs on your Android phone. Only numeric measurements reach this laptop.")
st.warning("This estimates visible head position, not attention or learning. Looking down can mean reading, writing or using a phone.")

if "engine" not in st.session_state:
    st.session_state.engine = RuleEngine()
    st.session_state.reader = None
    st.session_state.devices = []
    st.session_state.history = deque(maxlen=1500)
    st.session_state.events = deque(maxlen=100)
    st.session_state.labels = deque(maxlen=100)
    st.session_state.latest = None
    st.session_state.latest_capture = None
    st.session_state.last_status = UNKNOWN
    st.session_state.last_reminder = float("-inf")
    st.session_state.reminder_until = 0
    st.session_state.source = None
    st.session_state.paused_before = False


def record_event(text):
    st.session_state.events.append({"time_utc": datetime.now(timezone.utc).isoformat(), "event": text})
    LOG.info(text)


with st.sidebar:
    st.header("USB connection")
    adb_path = st.text_input("ADB executable (blank auto-detects)", placeholder=r"D:\Android\platform-tools\adb.exe")
    if st.button("Refresh devices"):
        try:
            st.session_state.devices = list_devices(find_adb(adb_path))
            if not st.session_state.devices:
                st.info("No Android phone found. Use a data cable, enable USB debugging, then approve the prompt on the unlocked phone.")
        except Exception as exc:
            st.error(str(exc))
    devices = st.session_state.devices
    device = st.selectbox("Phone", devices, format_func=lambda d: f"{d['serial']} — {d['state']} {d['description']}", index=0 if devices else None)
    if device and device["state"] != "device":
        st.warning("Unlock the phone and approve USB debugging. If offline, reconnect the cable.")
    if st.button("Connect dashboard", disabled=not device or device["state"] != "device"):
        try:
            if st.session_state.reader:
                st.session_state.reader.stop()
            selected_adb = find_adb(adb_path)
            # A calibration is specific to this device and camera position.
            if st.session_state.source != device["serial"]:
                st.session_state.engine.clear_calibration()
            st.session_state.source = device["serial"]
            st.session_state.engine.reset("Connected; waiting for fresh data.")
            st.session_state.latest = None
            st.session_state.latest_capture = None
            st.session_state.reader = UsbReader(selected_adb, device["serial"])
            st.session_state.reader.start()
            record_event("USB connection requested. Open the phone app and press Start.")
        except Exception as exc:
            st.error(str(exc))
    if st.button("Disconnect dashboard", disabled=st.session_state.reader is None):
        st.session_state.reader.stop()
        st.session_state.reader = None
        st.session_state.latest_capture = None
        st.session_state.engine.reset("Dashboard disconnected.")
        record_event("Dashboard disconnected. Stop the camera using the phone's Stop button.")
    st.caption("Disconnecting this dashboard does not control the phone camera. Use Stop on the phone.")
    paused = st.toggle("Pause assessment", value=False)
    if paused != st.session_state.paused_before:
        st.session_state.engine.cancel_calibration()
        st.session_state.engine.reset("Assessment paused." if paused else "Assessment resumed; timers reset.")
        st.session_state.paused_before = paused
    st.caption("Pause affects rules only; phone capture continues until you stop it on the phone.")
    st.header("Rule settings")
    yaw_limit = st.slider("Allowed horizontal angle ± degrees", 1, 90, 20)
    pitch_limit = st.slider("Allowed vertical angle ± degrees", 1, 90, 15)
    away = st.slider("Outside-position delay (seconds)", 1, 30, 5)
    recovery = st.slider("Recovery delay (seconds)", 0.2, 10.0, 2.0, 0.2)
    alpha = st.slider("Smoothing: higher responds faster", 0.05, 1.0, 0.3, 0.05)
    engine = st.session_state.engine
    engine.update_settings(Settings(yaw_limit, pitch_limit, away, recovery, alpha))

st.subheader("1. Calibrate normal study positions")
st.caption("Prop the phone so your face remains visible when reading the screen and writing. Hold each normal position steadily for five seconds. Recalibrate after moving the camera.")
columns = st.columns(4)
if columns[0].button("Calibrate screen", disabled=paused):
    engine.begin_calibration("screen")
if columns[1].button("Calibrate notebook", disabled=paused):
    engine.begin_calibration("notebook")
if columns[2].button("Cancel calibration"):
    engine.cancel_calibration()
if columns[3].button("Clear calibration"):
    engine.clear_calibration()


@st.fragment(run_every=0.25)
def live_dashboard():
    engine = st.session_state.engine
    reader = st.session_state.reader
    now = time.monotonic()
    if reader:
        batch, gap = reader.drain()
        connection = reader.snapshot()
        if gap:
            engine.reset("Dashboard fell behind; old data discarded and timers reset.")
        for received in batch:
            m = received.measurement
            st.session_state.latest = m.as_dict()
            st.session_state.latest_capture = received.capture_time
            if not paused:
                previous_run = engine.last_identity[0] if engine.last_identity else None
                if previous_run and previous_run != m.run_id:
                    record_event("Phone monitoring run changed; decision timers reset. Recalibrate if the camera moved.")
                engine.process(m)
            snapshot = engine.snapshot()
            st.session_state.history.append({"host_received_utc": datetime.now(timezone.utc).isoformat(),
                                             **m.as_dict(), **snapshot})
        if not connection["alive"]:
            engine.reset(connection["error"] or "USB reader stopped. Reconnect the dashboard.")
        elif st.session_state.latest_capture is None or now - st.session_state.latest_capture > 1:
            engine.reset("No fresh measurements within one second. Start the phone app or check the USB connection.")
        st.caption(f"USB: {connection['status']} · accepted {connection['accepted']} · discarded {connection['discarded']}")
        if connection["error"]:
            st.error(connection["error"])
    else:
        engine.reset("Connect an authorized USB phone to begin.")
    if paused:
        engine.reset("Assessment paused; measurements are not being assessed.")
    if engine.status != st.session_state.last_status:
        record_event(f"{engine.status}: {engine.reason}")
        if engine.status == OFF_TASK and now - st.session_state.last_reminder >= 30:
            st.session_state.last_reminder = now
            st.session_state.reminder_until = now + 8
        st.session_state.last_status = engine.status
    if engine.status == OFF_TASK and now < st.session_state.reminder_until:
        st.info("Have you moved away from your work? If you're ready, return to a comfortable study position.")
    st.subheader("2. Live assessment")
    {UNKNOWN: st.warning, STUDYING: st.success, OFF_TASK: st.info}[engine.status](engine.status)
    st.write(engine.reason)
    st.caption(engine.calibration_message)
    latest = st.session_state.latest or {}
    metrics = st.columns(4)
    for col, name, label in zip(metrics, ("face_count", "yaw", "pitch", "roll"), ("Faces", "Yaw / sideways", "Pitch / up-down", "Roll / tilt")):
        value = latest.get(name)
        col.metric(label, "—" if value is None else f"{value:g}" + ("°" if name != "face_count" else ""))
    if st.session_state.latest_capture is not None:
        st.caption(f"Displayed sample age: {max(0, now - st.session_state.latest_capture):.1f}s. Stale values are diagnostic only.")
    st.write("Saved normal positions", engine.profiles or "Not calibrated")
    with st.expander("Measurements and rule details"):
        st.json({"latest_raw_measurement": latest, "decision": engine.snapshot()})
        if st.session_state.history:
            chart = [{"sample": i, "yaw": r.get("yaw"), "pitch": r.get("pitch")}
                     for i, r in enumerate(list(st.session_state.history)[-150:])]
            st.line_chart(chart, x="sample", y=["yaw", "pitch"])
    st.subheader("3. Mark what was actually happening")
    st.caption("These are your manual labels, not model conclusions. They label this moment, not an entire interval.")
    label_columns = st.columns(3)
    for column, label in zip(label_columns, ("Normal studying", "Off-task", "Cannot assess")):
        if column.button(label):
            st.session_state.labels.append({"time_utc": datetime.now(timezone.utc).isoformat(),
                                            "label": label, "measurement": latest, "decision": engine.snapshot()})
            st.toast(f"Marked: {label}")
    with st.expander("Event timeline and manual labels"):
        st.write(list(st.session_state.events)[::-1])
        st.write(list(st.session_state.labels)[::-1])
    st.subheader("4. Optional export")
    st.caption("Downloads may include personal calibration and numeric face measurements. Nothing is saved to a file automatically.")
    if st.button("Prepare export snapshot"):
        st.session_state.export_settings = json.dumps({"schema_version": 1, "decision": engine.snapshot(),
            "note": "Calibration is person- and camera-specific."}, indent=2)
        st.session_state.export_session = json.dumps({"schema_version": 1,
            "settings_and_calibration": engine.snapshot(), "measurements": list(st.session_state.history),
            "labels": list(st.session_state.labels), "events": list(st.session_state.events)}, indent=2)
    if "export_settings" in st.session_state:
        st.caption("Downloads contain the snapshot from the last time you pressed Prepare, not a continuously updated recording.")
        export_columns = st.columns(2)
        export_columns[0].download_button("Download settings and calibration", st.session_state.export_settings,
            "calibration_settings.json", "application/json", on_click="ignore")
        export_columns[1].download_button("Download recent measurements and labels", st.session_state.export_session,
            "study_session.json", "application/json", on_click="ignore")


live_dashboard()
