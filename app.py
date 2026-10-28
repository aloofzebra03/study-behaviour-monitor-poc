"""USB-only phone-facing monitor. Run: python -m streamlit run app.py."""
import json
import logging
import time
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
from html import escape

import streamlit as st

from study_monitor.rules import FACING, LOOKING_AWAY, UNKNOWN, RuleEngine
from study_monitor.usb import UsbReader, find_adb, list_devices

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOG = logging.getLogger("phone_dashboard")
st.set_page_config(page_title="Phone screen monitor", layout="wide")
st.markdown("""
<style>
  .stMainBlockContainer { padding-top: 3.5rem; }
  .phone-status { border: 1px solid; border-radius: 22px; padding: 30px;
                  min-height: 290px; display: flex; flex-direction: column; justify-content: center; }
  .phone-status.test { min-height: 350px; padding: 40px; text-align: center; }
  .phone-status.facing { background: #eaf8f1; border-color: #74b99b; color: #123e2f; }
  .phone-status.away { background: #fff2e8; border-color: #dba16e; color: #74380d; }
  .phone-status.unknown { background: #f1f4f8; border-color: #aab8c9; color: #33465e; }
  .phone-status .eyebrow { font-size: .82rem; font-weight: 700; letter-spacing: .14em; margin-bottom: 16px; }
  .phone-status .status-title { font-size: clamp(2.5rem, 4.5vw, 4.8rem); font-weight: 850;
                               line-height: 1.05; letter-spacing: -.035em; margin: 0 0 20px; }
  .phone-status.test .status-title { font-size: clamp(3rem, 7vw, 6rem); }
  .phone-status .reason { font-size: 1rem; line-height: 1.5; margin: 0; }
  @media (max-width: 700px) {
    .phone-status, .phone-status.test { min-height: 250px; padding: 24px; }
  }
</style>
""", unsafe_allow_html=True)
st.title("Phone screen monitor")
st.caption("ML Kit runs on your phone · USB-only POC · Head direction estimate, not exact eye gaze or attention")

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
        st.session_state.notice = "Settings imported and saved for this browser session. They are now active."
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
    st.divider()
    st.subheader("Import settings")
    st.file_uploader("Load a tuned settings file (.json)", type=["json"], key="profile_upload", on_change=load_uploaded_profile)
    st.caption("Use a file downloaded after tuning. This updates the current dashboard, not the phone model or code defaults.")

def render_tuning_controls():
    engine = st.session_state.engine
    st.subheader("Tune the settings")
    st.caption("The result stays alongside these controls. Changes apply to the live preview immediately.")
    yaw = st.slider("Allowed sideways turn ± degrees", 1.0, 90.0, float(engine.settings.yaw_tolerance), 1.0, key="tune_yaw_tolerance")
    pitch = st.slider("Allowed up/down tilt ± degrees", 1.0, 90.0, float(engine.settings.pitch_tolerance), 1.0, key="tune_pitch_tolerance")
    away = st.slider("Looking-away delay (seconds)", 1.0, 30.0, float(engine.settings.away_seconds), 0.5, key="tune_away_seconds")
    recovery = st.slider("Facing-screen delay (seconds)", 0.2, 10.0, float(engine.settings.recovery_seconds), 0.2, key="tune_recovery_seconds")
    alpha = st.slider("Smoothing: higher responds faster", 0.05, 1.0, float(engine.settings.smoothing_alpha), 0.05, key="tune_smoothing_alpha")
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
    capturing = engine.calibration is not None
    st.button("Save settings and test", type="primary", on_click=save_and_test, disabled=capturing, use_container_width=True)
    st.download_button("Download tuned settings (.json)", json.dumps(engine.export_profile(), indent=2),
                       "phone_screen_settings.json", "application/json", on_click="ignore", disabled=capturing,
                       use_container_width=True)
    st.caption("Share this JSON so someone else can import your settings. Download includes current edits; Save makes them active in Test. A captured reference is person- and camera-specific.")


def render_status_card(engine):
    title, style = {
        FACING: ("FACING THE SCREEN", "facing"),
        LOOKING_AWAY: ("LOOKING AWAY", "away"),
        UNKNOWN: ("CANNOT ASSESS YET", "unknown"),
    }[engine.status]
    size = "" if tuning else " test"
    # Only fixed class names are used; dynamic text is always escaped.
    st.markdown(f'<section class="phone-status {style}{size}" role="status" aria-live="polite">'
                f'<div class="eyebrow">LIVE HEAD-DIRECTION RESULT</div>'
                f'<div class="status-title">{title}</div>'
                f'<p class="reason">{escape(engine.reason)}</p></section>', unsafe_allow_html=True)
    if engine.candidate and engine.candidate != engine.status:
        delay = engine.settings.recovery_seconds if engine.candidate == FACING else engine.settings.away_seconds
        st.progress(min(engine.elapsed / delay, 1.0), text=f"Confirming: {engine.candidate} · {engine.elapsed:.1f}/{delay:g}s")


@st.fragment(run_every=0.25)
def live_dashboard():
    engine = st.session_state.engine
    reader = st.session_state.reader
    now = time.monotonic()
    connection = None
    reference_completed = False
    if reader:
        batch, gap = reader.drain()
        connection = reader.snapshot()
        if gap:
            engine.reset("Dashboard fell behind; old samples discarded and timers reset.")
        for received in batch:
            measurement = received.measurement
            st.session_state.latest = measurement.as_dict()
            st.session_state.latest_capture = received.capture_time
            capturing = engine.calibration is not None
            engine.process(measurement)
            reference_completed |= capturing and engine.calibration is None
            st.session_state.history.append({"time_utc": datetime.now(timezone.utc).isoformat(),
                                             **measurement.as_dict(), **engine.snapshot()})
        if not connection["alive"]:
            engine.reset(connection["error"] or "USB reader stopped; reconnect the dashboard.")
        elif st.session_state.latest_capture is None or now - st.session_state.latest_capture > 1:
            engine.reset("No fresh data. Keep the phone app open, grant camera access and press Start.")
    else:
        engine.reset("Connect a USB phone to begin.")
    if engine.status != st.session_state.last_status:
        record_event(f"{engine.status}: {engine.reason}")
        st.session_state.last_status = engine.status
    if reference_completed:
        # Refresh the download payload and re-enable Save after async capture.
        st.session_state.notice = "Front-facing reference captured. You can now save or download these settings."
        st.rerun()
    st.subheader("Live result")
    render_status_card(engine)
    if connection:
        st.caption(f"USB: {connection['status']} · samples {connection['accepted']} · discarded {connection['discarded']}")
        if connection["error"]:
            st.error(connection["error"])
    if engine.calibration is not None:
        st.caption(engine.calibration_message)
    latest = st.session_state.latest or {}
    fresh = bool(connection and connection["alive"] and st.session_state.latest_capture is not None
                 and now - st.session_state.latest_capture <= 1)
    for col, name, label in zip(st.columns(3), ("face_count", "yaw", "pitch"), ("Faces", "Sideways / yaw", "Up-down / pitch")):
        value = latest.get(name) if fresh else None
        col.metric(label, "—" if value is None else f"{value:g}" + ("°" if name != "face_count" else ""))
    with st.expander("Model measurements and rule details"):
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


if tuning:
    controls, result = st.columns([1, 1.5], gap="large", vertical_alignment="top")
    with controls:
        render_tuning_controls()
    with result:
        live_dashboard()
else:
    engine = st.session_state.engine
    st.caption(f"Saved settings: sideways ±{engine.settings.yaw_tolerance:g}°, up/down ±{engine.settings.pitch_tolerance:g}°, "
               f"away delay {engine.settings.away_seconds:g}s, facing delay {engine.settings.recovery_seconds:g}s. No calibration required.")
    live_dashboard()
    st.download_button("Download active settings (.json)", json.dumps(engine.export_profile(), indent=2),
                       "phone_screen_settings.json", "application/json", on_click="ignore")
st.caption("USB testing must run on the laptop connected to the phone. Streamlit Cloud cannot access that laptop's USB devices.")
