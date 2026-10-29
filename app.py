"""USB-only reading/writing study-posture monitor. Run: python -m streamlit run app.py."""
import json
import logging
import time
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
from html import escape

import streamlit as st

from study_monitor.rules import NORMAL, AWAY, UNKNOWN, PAUSED, POSITIONS, SIDES, HEIGHTS, RuleEngine
from study_monitor.usb import UsbReader, find_adb, list_devices

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOG = logging.getLogger("study_dashboard")
st.set_page_config(page_title="Study posture monitor", layout="wide")
st.markdown("""
<style>
  .stMainBlockContainer { padding-top: 3.5rem; }
  .phone-status { border: 1px solid; border-radius: 22px; padding: 30px;
                  min-height: 290px; display: flex; flex-direction: column; justify-content: center; }
  .phone-status.test { min-height: 350px; padding: 40px; text-align: center; }
  .phone-status.facing { background: #eaf8f1; border-color: #74b99b; color: #123e2f; }
  .phone-status.paused { background: #eef2ff; border-color: #a5b4fc; color: #334375; }
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
st.title("Study posture monitor")
st.caption("Phone monitors reading/writing posture over USB. Not an eye-gaze, attention or learning measurement.")

# Old phone-facing profiles cannot silently become valid study references.
if "engine" not in st.session_state or getattr(st.session_state.engine, "version", None) != 3:
    old_reader = st.session_state.get("reader")
    if old_reader:
        old_reader.stop()
    for key in list(st.session_state):
        if key.startswith("tune_") or key in ("camera_side", "camera_height", "profile_upload"):
            del st.session_state[key]
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
    st.session_state.connected_serial = None
    st.session_state.break_mode = False
    st.session_state.reuse_positions = False


def record_event(text):
    st.session_state.events.append({"time_utc": datetime.now(timezone.utc).isoformat(), "event": text})
    LOG.info(text)


def seed_tuning_widgets():
    for name, value in st.session_state.engine.export_profile()["settings"].items():
        st.session_state[f"tune_{name}"] = float(value)
    st.session_state.camera_side = st.session_state.engine.placement["side"]
    st.session_state.camera_height = st.session_state.engine.placement["height"]


def switch_mode():
    st.session_state.engine.load_profile(st.session_state.saved_profile, reuse_positions=True)
    seed_tuning_widgets()
    record_event(f"Mode changed to {st.session_state.mode}; decision timers reset.")


def save_and_test():
    engine = st.session_state.engine
    if not engine.ready or engine.calibration is not None or engine.paused:
        st.session_state.notice = "Finish reading/writing setup and resume monitoring before saving."
        return
    st.session_state.saved_profile = engine.export_profile()
    engine.load_profile(st.session_state.saved_profile, reuse_positions=True)
    st.session_state.mode = "Test"
    st.session_state.notice = "Settings saved for this browser session. Download them to reuse them later."
    record_event("Saved reading/writing setup and switched to Test.")


def invalidate_setup(reason):
    """Invalidate live and saved references, not just the current preview."""
    engine = st.session_state.engine
    engine.clear_positions(reason)
    saved = st.session_state.saved_profile
    st.session_state.saved_profile = {**engine.export_profile(), "settings": saved["settings"]}
    st.session_state.notice = reason


def open_setup():
    st.session_state.mode = "Tune / setup"
    switch_mode()


def redo_setup():
    invalidate_setup("Phone, book or seating moved. Capture reading and writing again.")
    st.session_state.mode = "Tune / setup"
    seed_tuning_widgets()


def toggle_break():
    st.session_state.engine.set_paused(st.session_state.break_mode)
    record_event("Break started." if st.session_state.break_mode else "Monitoring resumed; timers reset.")


def begin_capture(position):
    st.session_state.engine.begin_calibration(position)
    record_event(f"Capturing normal {position} position.")


def load_uploaded_profile():
    uploaded = st.session_state.get("profile_upload")
    if uploaded is None:
        st.session_state.notice = "Choose a settings JSON file first."
        return
    try:
        if uploaded.size > 16000:
            raise ValueError("Settings file is too large.")
        st.session_state.engine.load_profile(
            json.loads(uploaded.getvalue()), reuse_positions=st.session_state.reuse_positions)
        st.session_state.saved_profile = st.session_state.engine.export_profile()
        seed_tuning_widgets()
        st.session_state.notice = (
            "Same-setup study references loaded. Redo setup if anything moved."
            if st.session_state.engine.ready else
            "Thresholds imported. Capture reading and writing for your own camera placement.")
    except (ValueError, TypeError, KeyError) as exc:
        st.session_state.notice = f"Could not load settings: {exc}"


mode = st.radio("Mode", ["Test", "Tune / setup"], horizontal=True, key="mode", on_change=switch_mode)
tuning = mode == "Tune / setup"
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
            if st.session_state.connected_serial and st.session_state.connected_serial != device["serial"]:
                invalidate_setup("Different phone selected. Capture reading and writing again.")
                st.session_state.history.clear()
                st.session_state.labels.clear()
            st.session_state.connected_serial = device["serial"]
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
    st.toggle("Taking a break", key="break_mode", on_change=toggle_break)
    st.caption("Break pauses assessment, not the camera. Resume when ready.")
    st.button("Phone moved / redo setup", on_click=redo_setup)
    st.divider()
    st.subheader("Import settings")
    st.file_uploader("Load a tuned settings file (.json)", type=["json"], key="profile_upload")
    st.checkbox("Reuse recorded positions: same person, phone, book and placement", key="reuse_positions")
    st.button("Apply imported settings", on_click=load_uploaded_profile)
    st.caption("Normally import thresholds only and capture your own positions. Old phone-facing files never supply study references.")

def render_tuning_controls():
    engine = st.session_state.engine
    st.subheader("Set up your usual study positions")
    st.caption("Keep the phone fixed. A front-diagonal view often preserves face visibility better than a steep side/top view.")
    placement = st.columns(2)
    side = placement[0].selectbox("Phone position", SIDES, index=SIDES.index(engine.placement["side"]),
        format_func=lambda value: {"left": "On the left", "front": "In front", "right": "On the right"}[value], key="camera_side")
    height = placement[1].selectbox("Camera height", HEIGHTS, index=HEIGHTS.index(engine.placement["height"]),
        format_func=lambda value: {"above": "Above face level", "level": "Around face level", "below": "Below face level"}[value], key="camera_height")
    if engine.set_placement(side, height):
        invalidate_setup("Placement changed. Capture reading and writing for this position.")
    st.caption("These labels record the setup; captured head angles—not the labels—drive the rules.")
    buttons = st.columns(2)
    capturing = engine.calibration is not None
    buttons[0].button("Capture reading (5s)", disabled=capturing or engine.paused,
                      on_click=begin_capture, args=("reading",))
    buttons[1].button("Capture writing (5s)", disabled=capturing or engine.paused,
                      on_click=begin_capture, args=("writing",))
    if engine.calibration is not None:
        st.button("Cancel capture", on_click=engine.cancel_calibration)
    for name in POSITIONS:
        st.caption(f"{name.capitalize()}: {'captured' if name in engine.study_positions else 'not captured yet'}")
    st.caption(engine.calibration_message)
    st.caption("Read or write normally during capture. Your face must remain visible in BOTH activities. If detection fails, adjust the phone; missing faces are not counted as distraction.")
    with st.expander("Tune tolerances and timing", expanded=engine.ready):
        yaw = st.slider("Sideways tolerance around either posture ± degrees", 1.0, 90.0, float(engine.settings.yaw_tolerance), 1.0, key="tune_yaw_tolerance")
        pitch = st.slider("Up/down tolerance around either posture ± degrees", 1.0, 90.0, float(engine.settings.pitch_tolerance), 1.0, key="tune_pitch_tolerance")
        away = st.slider("Check-in delay outside study positions (seconds)", 1.0, 60.0, float(engine.settings.away_seconds), 0.5, key="tune_away_seconds")
        recovery = st.slider("Return-to-study confirmation (seconds)", 0.2, 10.0, float(engine.settings.recovery_seconds), 0.2, key="tune_recovery_seconds")
        alpha = st.slider("Smoothing: higher responds faster", 0.05, 1.0, float(engine.settings.smoothing_alpha), 0.05, key="tune_smoothing_alpha")
    engine.update_settings(replace(engine.settings, yaw_tolerance=yaw, pitch_tolerance=pitch,
                                   away_seconds=away, recovery_seconds=recovery, smoothing_alpha=alpha))
    capturing = engine.calibration is not None
    st.button("Save setup and test", type="primary", on_click=save_and_test,
              disabled=capturing or not engine.ready or engine.paused, use_container_width=True)
    st.download_button("Download study settings (.json)", json.dumps(engine.export_profile(), indent=2),
                       "study_monitor_settings.json", "application/json", on_click="ignore",
                       disabled=capturing, use_container_width=True)
    st.caption("The JSON includes thresholds and recorded positions. Other users should normally import thresholds only and capture their own setup.")


def render_status_card(engine):
    if engine.paused:
        title, style = "TAKING A BREAK", "paused"
    elif engine.calibration is not None:
        title, style = f"LEARNING {engine.calibration['position'].upper()} POSITION", "unknown"
    elif not engine.ready:
        title, style = "STUDY SETUP NEEDED", "unknown"
    else:
        title, style = {
            NORMAL: ("NORMAL STUDY POSTURE", "facing"),
            AWAY: ("POSSIBLY AWAY FROM WORK", "away"),
            UNKNOWN: ("CANNOT ASSESS", "unknown"),
        }[engine.status]
    size = "" if tuning else " test"
    # Only fixed class names are used; dynamic text is always escaped.
    st.markdown(f'<section class="phone-status {style}{size}" role="status" aria-live="polite">'
                f'<div class="eyebrow">STUDY-POSTURE ESTIMATE</div>'
                f'<div class="status-title">{title}</div>'
                f'<p class="reason">{escape(engine.reason)}</p></section>', unsafe_allow_html=True)
    if engine.ready and not engine.paused and engine.candidate and engine.candidate != engine.status:
        delay = engine.settings.recovery_seconds if engine.candidate == NORMAL else engine.settings.away_seconds
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
        st.session_state.notice = "Study position captured. Capture both reading and writing, then save the setup."
        st.rerun()
    st.subheader("Live result")
    render_status_card(engine)
    if engine.status == AWAY:
        st.info("Ready to continue, or would you like a break? Use Taking a break to pause monitoring—short rests are fine.")
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
            for col, label in zip(st.columns(3), ("Normal study posture", "Away from work", "Cannot assess")):
                if col.button(label):
                    st.session_state.labels.append({"time_utc": datetime.now(timezone.utc).isoformat(),
                                                    "label": label, "measurement": latest, "decision": engine.snapshot()})
                    st.toast(f"Marked: {label}")
            if st.button("Prepare recent data export"):
                st.session_state.export_session = json.dumps({"schema_version": 3, "profile": engine.export_profile(),
                    "measurements": list(st.session_state.history), "labels": list(st.session_state.labels),
                    "events": list(st.session_state.events)}, indent=2)
            if "export_session" in st.session_state:
                st.download_button("Download prepared data", st.session_state.export_session,
                                   "study_monitor_session.json", "application/json", on_click="ignore")
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
    st.caption(f"Study tolerances: sideways ±{engine.settings.yaw_tolerance:g}°, up/down ±{engine.settings.pitch_tolerance:g}° around either recorded posture; check-in after {engine.settings.away_seconds:g}s away.")
    if not engine.ready:
        st.button("Set up reading and writing", type="primary", on_click=open_setup)
        st.caption("Place the phone first. Capture both normal activities once; facing the camera is not a study requirement.")
    else:
        st.caption("Use this setup only while the person, phone, book and seating positions are unchanged.")
    live_dashboard()
    st.download_button("Download active study settings (.json)", json.dumps(engine.export_profile(), indent=2),
                       "study_monitor_settings.json", "application/json", on_click="ignore")

st.caption("USB testing must run on the laptop connected to the phone. Streamlit Cloud cannot access that laptop's USB devices.")
