"""USB-only phone-facing monitor. Run: python -m streamlit run app.py."""
import json
import logging
import time
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone

import streamlit as st

from study_monitor.rules import FACING, LOOKING_AWAY, UNKNOWN, RuleEngine
from study_monitor.usb import UsbReader, find_adb, list_devices

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOG = logging.getLogger("phone_dashboard")
st.set_page_config(page_title="Phone screen monitor", layout="wide")
st.title("Is the student facing the phone?")
st.caption("ML Kit runs on your phone. Only numeric measurements reach this laptop over USB.")
st.info("This estimates head direction, not exact eye gaze or attention. Keep the camera near eye level and the phone app open.")

# Upgrade browser sessions that still have the older two-position engine.
if "engine" not in st.session_state or getattr(st.session_state.engine, "version", None) != 2:
    old_reader = st.session_state.get("reader")
    if old_reader:
        old_reader.stop()
    st.session_state.engine = RuleEngine()
    st.session_state.saved_profile = st.session_state.engine.export_profile()
    st.session_state.reader = None
    st.session_state.devices = []
    st.session_state.history = deque(maxlen=1500)
    st.session_state.events = deque(maxlen=100)
    st.session_state.labels = deque(maxlen=100)
    st.session_state.latest = None
    st.session_state.latest_capture = None
    st.session_state.last_status = UNKNOWN
    st.session_state.mode = "Test"
    st.session_state.notice = ""


def record_event(text):
    st.session_state.events.append({"time_utc": datetime.now(timezone.utc).isoformat(), "event": text})
    LOG.info(text)


def seed_tuning_widgets():
    for name, value in st.session_state.engine.export_profile()["settings"].items():
        st.session_state[f"tune_{name}"] = float(value)


def switch_mode():
    st.session_state.engine.load_profile(st.session_state.saved_profile)
    seed_tuning_widgets()
    record_event(f"Mode changed to {st.session_state.mode}; decision timers reset.")


def save_and_test():
    engine = st.session_state.engine
    engine.cancel_calibration()
    st.session_state.saved_profile = engine.export_profile()
    engine.load_profile(st.session_state.saved_profile)
    st.session_state.mode = "Test"
    st.session_state.notice = "Settings saved for this browser session. Download them to reuse them later."
    record_event("Saved phone-facing settings and switched to Test.")


def load_uploaded_profile():
    uploaded = st.session_state.get("profile_upload")
    if uploaded is None:
        return
    try:
        if uploaded.size > 16000:
            raise ValueError("Settings file is too large.")
        st.session_state.engine.load_profile(json.loads(uploaded.getvalue()))
        st.session_state.saved_profile = st.session_state.engine.export_profile()
        seed_tuning_widgets()
        st.session_state.notice = "Settings loaded. Switch to Test to use them."
    except (ValueError, TypeError, KeyError) as exc:
        st.session_state.notice = f"Could not load settings: {exc}"


mode = st.radio("Mode", ["Test", "Tune / calibrate"], horizontal=True, key="mode", on_change=switch_mode)
tuning = mode == "Tune / calibrate"
if st.session_state.notice:
    st.caption(st.session_state.notice)

with st.sidebar:
    st.header("USB connection")
    with st.expander("Advanced USB setup"):
        adb_path = st.text_input("ADB executable (blank auto-detects)", placeholder=r"D:\Android\platform-tools\adb.exe")
    if st.button("Refresh devices"):
        try:
            st.session_state.devices = list_devices(find_adb(adb_path))
            if not st.session_state.devices:
                st.warning("No phone found. Check USB debugging, the data cable and the authorization prompt on the unlocked phone.")
        except Exception as exc:
            st.error(str(exc))
    devices = st.session_state.devices
    device = st.selectbox("Phone", devices, format_func=lambda d: f"{d['serial']} — {d['state']}", index=0 if devices else None)
    if device and device["state"] != "device":
        st.warning("Unlock the phone and approve USB debugging. If offline, reconnect it.")
    if st.button("Connect", disabled=not device or device["state"] != "device"):
        try:
            if st.session_state.reader:
                st.session_state.reader.stop()
            st.session_state.engine.reset("Connected; waiting for fresh phone measurements.")
            st.session_state.latest = None
            st.session_state.latest_capture = None
            st.session_state.reader = UsbReader(find_adb(adb_path), device["serial"])
            st.session_state.reader.start()
            record_event("USB connected. Open the phone app and press Start.")
        except Exception as exc:
            st.error(str(exc))
    if st.button("Disconnect", disabled=st.session_state.reader is None):
        st.session_state.reader.stop()
        st.session_state.reader = None
        st.session_state.latest_capture = None
        st.session_state.engine.reset("Dashboard disconnected.")
        record_event("Dashboard disconnected. Stop the camera on the phone.")
    st.caption("Disconnect stops only the USB reader. Start / Stop on the phone controls its camera.")

engine = st.session_state.engine
if tuning:
    st.subheader("Tune settings, then save and test")
    st.caption("No notebook position. A personal front-facing reference is optional; default angles work without calibration.")
    cols = st.columns(2)
    yaw = cols[0].slider("Allowed sideways turn ± degrees", 1.0, 90.0, float(engine.settings.yaw_tolerance), 1.0, key="tune_yaw_tolerance")
    pitch = cols[1].slider("Allowed up/down tilt ± degrees", 1.0, 90.0, float(engine.settings.pitch_tolerance), 1.0, key="tune_pitch_tolerance")
    away = cols[0].slider("Looking-away delay (seconds)", 1.0, 30.0, float(engine.settings.away_seconds), 0.5, key="tune_away_seconds")
    recovery = cols[1].slider("Facing-screen delay (seconds)", 0.2, 10.0, float(engine.settings.recovery_seconds), 0.2, key="tune_recovery_seconds")
    alpha = cols[0].slider("Smoothing: higher responds faster", 0.05, 1.0, float(engine.settings.smoothing_alpha), 0.05, key="tune_smoothing_alpha")
    engine.update_settings(replace(engine.settings, yaw_tolerance=yaw, pitch_tolerance=pitch,
                                   away_seconds=away, recovery_seconds=recovery, smoothing_alpha=alpha))
    with st.expander("Optional: capture a front-facing reference"):
        st.caption("Look directly at the phone and capture for five seconds. Test mode does not require this.")
        buttons = st.columns(3)
        if buttons[0].button("Capture front-facing position"):
            engine.begin_calibration()
        if buttons[1].button("Cancel capture"):
            engine.cancel_calibration()
        if buttons[2].button("Use default front-facing angles"):
            engine.use_default_reference()
        st.caption(engine.calibration_message)
    st.button("Save settings and test", type="primary", on_click=save_and_test)
    with st.expander("Reuse settings on another local dashboard"):
        st.file_uploader("Load phone-screen settings JSON", type=["json"], key="profile_upload", on_change=load_uploaded_profile)
        st.download_button("Download current settings", json.dumps(engine.export_profile(), indent=2),
                           "phone_screen_settings.json", "application/json", on_click="ignore")
        st.caption("Captured reference angles are person- and camera-specific. Reused thresholds still need checking on another setup.")
else:
    st.caption(f"Saved settings: sideways ±{engine.settings.yaw_tolerance:g}°, up/down ±{engine.settings.pitch_tolerance:g}°, "
               f"away delay {engine.settings.away_seconds:g}s, facing delay {engine.settings.recovery_seconds:g}s. No calibration required.")


@st.fragment(run_every=0.25)
def live_dashboard():
    engine = st.session_state.engine
    reader = st.session_state.reader
    now = time.monotonic()
    if reader:
        batch, gap = reader.drain()
        connection = reader.snapshot()
        if gap:
            engine.reset("Dashboard fell behind; old samples discarded and timers reset.")
        for received in batch:
            measurement = received.measurement
            st.session_state.latest = measurement.as_dict()
            st.session_state.latest_capture = received.capture_time
            engine.process(measurement)
            st.session_state.history.append({"time_utc": datetime.now(timezone.utc).isoformat(),
                                             **measurement.as_dict(), **engine.snapshot()})
        if not connection["alive"]:
            engine.reset(connection["error"] or "USB reader stopped; reconnect the dashboard.")
        elif st.session_state.latest_capture is None or now - st.session_state.latest_capture > 1:
            engine.reset("No fresh data. Keep the phone app open, grant camera access and press Start.")
        st.caption(f"USB: {connection['status']} · accepted {connection['accepted']} · discarded {connection['discarded']}")
        if connection["error"]:
            st.error(connection["error"])
    else:
        engine.reset("Connect a USB phone to begin.")
    if engine.status != st.session_state.last_status:
        record_event(f"{engine.status}: {engine.reason}")
        st.session_state.last_status = engine.status
    st.subheader("Live result")
    {UNKNOWN: st.warning, FACING: st.success, LOOKING_AWAY: st.info}[engine.status](engine.status)
    st.write(engine.reason)
    if engine.calibration is not None:
        st.caption(engine.calibration_message)
    latest = st.session_state.latest or {}
    with st.expander("Live model measurements and rule details", expanded=tuning):
        for col, name, label in zip(st.columns(3), ("face_count", "yaw", "pitch"), ("Faces", "Sideways / yaw", "Up-down / pitch")):
            value = latest.get(name)
            col.metric(label, "—" if value is None else f"{value:g}" + ("°" if name != "face_count" else ""))
        if st.session_state.latest_capture is not None:
            st.caption(f"Sample age: {max(0, now - st.session_state.latest_capture):.1f}s. Old values are diagnostic only.")
        st.json({"measurement": latest, "decision": engine.snapshot()})
    if tuning:
        with st.expander("Optional: mark observations and export recent data"):
            st.caption("Labels refer to this moment. They are your observations, not model-generated ground truth.")
            for col, label in zip(st.columns(3), ("Facing screen", "Looking away", "Cannot assess")):
                if col.button(label):
                    st.session_state.labels.append({"time_utc": datetime.now(timezone.utc).isoformat(),
                                                    "label": label, "measurement": latest, "decision": engine.snapshot()})
                    st.toast(f"Marked: {label}")
            if st.button("Prepare recent data export"):
                st.session_state.export_session = json.dumps({"schema_version": 2, "profile": engine.export_profile(),
                    "measurements": list(st.session_state.history), "labels": list(st.session_state.labels),
                    "events": list(st.session_state.events)}, indent=2)
            if "export_session" in st.session_state:
                st.download_button("Download prepared data", st.session_state.export_session,
                                   "phone_screen_session.json", "application/json", on_click="ignore")
            st.caption("Exports contain numeric face measurements and possibly personal reference angles. No video is saved.")
            st.write(list(st.session_state.events)[-10:])


live_dashboard()
st.caption("USB testing must run on the laptop connected to the phone. Streamlit Cloud cannot access that laptop's USB devices.")
