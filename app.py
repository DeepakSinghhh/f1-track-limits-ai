"""Pipeline runner: reads a video clip, runs the real CV -> Tier 1/2
pipeline (src/detector.py), and submits every candidate event to the
Tier 5 API (POST /events) for a steward to review in console/.

This used to also BE the steward review surface -- confirm/reject
buttons, trust bars, agent reasoning, its own override log. All of that
is retired in favour of console/ + src/api/, which do the same job
better: a live, multi-viewer queue with Section 5.10's evidence-before-
verdict ordering and real-time WebSocket updates, instead of a
duplicate, single-process copy of it running inside this script. What
this file is for now: getting a video clip's candidate events INTO that
queue in the first place -- console/ has no way to ingest a video
itself, and src/api/ has no way to run YOLO or read a calibration form.

Requires a running API (`uvicorn src.api.main:app`) to submit to; the
sidebar's "API base URL" field configures where, same pattern as
console/'s own setting.
"""
import math

import streamlit as st
import cv2
import httpx
import tempfile
import os
from dataclasses import asdict

from src.vision.calibrate import CalibrationError, calibrate
from src.detector import TrackLimitDetector
from src.render.incident import build_incident_annotations
from src.render.overlay import render_incident_clip, try_reencode_h264
from src.config import load_event_config
from src.track.build import build_straight_segment_track

CONFIG_PATH = "config/events/demo_clip.yaml"
EVIDENCE_CLIP_DIR = "data/clips"
DEFAULT_API_BASE_URL = "http://localhost:8000"

st.set_page_config(page_title="Apex Assist — Pipeline Runner", layout="wide")

# --- CUSTOM UI & FONT AWESOME ICONS ---
st.markdown("""
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
    .stApp {
        background-color: #0b0e14;
        color: #e6edf3;
    }
    .main-title {
        font-size: 2rem;
        font-weight: 900;
        color: #ffffff;
        border-left: 5px solid #ff1801;
        padding-left: 15px;
        text-transform: uppercase;
        letter-spacing: -0.5px;
    }
    .subtitle {
        color: #8b949e;
        font-size: 0.95rem;
        margin-bottom: 25px;
        padding-left: 20px;
    }
    section[data-testid="stSidebar"] {
        background-color: #161b22;
        border-right: 1px solid #30363d;
    }
    div[data-testid="column"] {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    }
    .stButton>button {
        background-color: #ff1801;
        color: white;
        font-weight: 700;
        border-radius: 6px;
        border: none;
        width: 100%;
    }
    .stButton>button:hover {
        background-color: #d91400;
    }
</style>
""", unsafe_allow_html=True)

# --- HEADER ---
st.markdown(
    '<p class="main-title"><i class="fa-solid fa-flag-checkered" '
    'style="color: #ff1801; margin-right: 10px;"></i>Apex Assist — Pipeline Runner</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="subtitle">Runs a video clip through detection and submits every candidate '
    'track-limit excursion to the steward console (src/api/ + console/) for review. '
    'This page does not review or decide anything itself — open console/ to confirm or '
    'reject what gets submitted here.</p>',
    unsafe_allow_html=True,
)

# --- SESSION STATE ---
if "findings" not in st.session_state:
    st.session_state.findings = []
if "processed_video" not in st.session_state:
    st.session_state.processed_video = None
if "calibration_bundle" not in st.session_state:
    st.session_state.calibration_bundle = None  # (CameraCalibration, TrackFrame, Boundary, heading_rad) or None
if "api_base_url" not in st.session_state:
    st.session_state.api_base_url = os.environ.get("APEX_API_BASE_URL", DEFAULT_API_BASE_URL)

# --- SIDEBAR: INGESTION & CONFIG ---
st.sidebar.markdown("### <i class='fa-solid fa-sliders'></i> Pipeline Ingestion", unsafe_allow_html=True)
if "video_path" not in st.session_state:
    st.session_state.video_path = None

# st.button only returns True on the render immediately after it's
# clicked -- persisting the choice in session_state is what lets a
# later, separate click on "Run Detection Pipeline" still see it.
if st.sidebar.button("⚡ Load Sample Race Clip"):
    st.session_state.video_path = "sample_video.mp4"

uploaded_file = st.sidebar.file_uploader("📁 Ingest Custom Video", type=["mp4", "avi"])
if uploaded_file is not None:
    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    tfile.write(uploaded_file.getvalue())
    st.session_state.video_path = tfile.name

st.sidebar.markdown("---")

with st.sidebar.expander("🎯 Calibration (optional) — real boundary & per-wheel geometry"):
    st.caption(
        "Without this, findings use the illustrative on-screen zone and always report "
        "INSUFFICIENT_EVIDENCE (no per-wheel data). With it, every point below is real: "
        "a homography fit from the correspondences you give, and a straight local track "
        "model from the two segment points — genuine VIOLATION findings become possible. "
        "Read pixel coordinates off the frame preview below once a clip is loaded."
    )

    if st.session_state.video_path and os.path.exists(st.session_state.video_path):
        _cap = cv2.VideoCapture(st.session_state.video_path)
        _ok, _first_frame = _cap.read()
        _cap.release()
        if _ok:
            st.image(cv2.cvtColor(_first_frame, cv2.COLOR_BGR2RGB), caption="First frame (for reading pixel coordinates)")

    st.markdown("**Point correspondences** (image pixel &rarr; world metres), at least 4:")
    image_points, world_points = [], []
    for i in range(4):
        c1, c2, c3, c4 = st.columns(4)
        u = c1.number_input(f"px u{i+1}", value=0.0, key=f"cal_u{i}")
        v = c2.number_input(f"px v{i+1}", value=0.0, key=f"cal_v{i}")
        x = c3.number_input(f"m x{i+1}", value=0.0, key=f"cal_x{i}")
        y = c4.number_input(f"m y{i+1}", value=0.0, key=f"cal_y{i}")
        image_points.append((u, v))
        world_points.append((x, y))

    st.markdown("**Local track segment** (world metres, direction of travel p1 &rarr; p2):")
    c1, c2 = st.columns(2)
    seg_p1 = (c1.number_input("p1 x", value=0.0, key="cal_p1x"), c1.number_input("p1 y", value=0.0, key="cal_p1y"))
    seg_p2 = (c2.number_input("p2 x", value=10.0, key="cal_p2x"), c2.number_input("p2 y", value=0.0, key="cal_p2y"))

    c1, c2 = st.columns(2)
    left_half_width_m = c1.number_input("Left half-width (m)", value=4.0, min_value=0.1, key="cal_left")
    right_half_width_m = c2.number_input("Right half-width (m)", value=4.0, min_value=0.1, key="cal_right")

    if st.button("Apply Calibration"):
        try:
            calibration = calibrate(image_points, world_points)
            heading_rad = math.atan2(seg_p2[1] - seg_p1[1], seg_p2[0] - seg_p1[0])
            event_config = load_event_config(CONFIG_PATH)
            track_frame, boundary = build_straight_segment_track(
                p1=seg_p1,
                p2=seg_p2,
                left_half_width_m=left_half_width_m,
                right_half_width_m=right_half_width_m,
                white_line_width_m=event_config.white_line_width_m,
            )
            st.session_state.calibration_bundle = (calibration, track_frame, boundary, heading_rad)
            st.success(f"Calibrated. Reprojection error: {calibration.reprojection_error_px:.2f}px.")
        except (CalibrationError, ValueError) as exc:
            st.session_state.calibration_bundle = None
            st.error(f"Calibration failed: {exc}")

    if st.session_state.calibration_bundle is not None:
        _cal, _, _, _heading = st.session_state.calibration_bundle
        st.caption(
            f"Active: reprojection error {_cal.reprojection_error_px:.2f}px, "
            f"heading {math.degrees(_heading):.1f}°. "
            f"Cleared automatically if this form is edited and not re-applied."
        )
        if st.button("Clear Calibration"):
            st.session_state.calibration_bundle = None
            st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("### <i class='fa-solid fa-server'></i> Steward Console API", unsafe_allow_html=True)
st.session_state.api_base_url = st.sidebar.text_input("API base URL", value=st.session_state.api_base_url)

st.sidebar.markdown("---")
st.sidebar.markdown("### <i class='fa-solid fa-gear'></i> Detection Parameters", unsafe_allow_html=True)
conf_threshold = st.sidebar.slider("YOLO Confidence Threshold", 0.3, 0.95, 0.5)
min_duration_frames = st.sidebar.slider("Minimum Event Duration (frames)", 1, 15, 4)

st.sidebar.markdown("---")
if st.session_state.calibration_bundle is not None:
    st.sidebar.caption(
        "**Calibrated run**: findings use a real homography and per-wheel geometry — "
        "genuine VIOLATION/NO_VIOLATION verdicts are possible, not just abstention. "
        "Still a single dominant-vehicle tracker (no per-car ID) and a straight local "
        "track model valid only near the segment you calibrated. Nothing here is "
        "auto-penalised or auto-struck regardless."
    )
else:
    st.sidebar.caption(
        "**Demo limitations**, stated rather than hidden: the drawn zone is an illustrative "
        "screen-space region, not a calibrated track boundary; detection uses a single "
        "reference point per vehicle, not per-wheel contact patches, so the rule engine "
        "correctly reports INSUFFICIENT_EVIDENCE for the Art. 33.3 wheel-count test on every "
        "candidate. Calibrate above to change that. Nothing here is auto-penalised or auto-struck."
    )

video_path = st.session_state.video_path
run_clicked = st.sidebar.button("▶️ Run Detection Pipeline") if video_path else False

# --- PIPELINE EXECUTION ---
if run_clicked and video_path and os.path.exists(video_path):
    api_base_url = st.session_state.api_base_url.rstrip("/")
    try:
        health = httpx.get(f"{api_base_url}/health", timeout=5.0)
        health.raise_for_status()
        st.sidebar.success(f"API reachable at {api_base_url} (agent {'on' if health.json().get('agent_enabled') else 'off'}).")
    except httpx.HTTPError as exc:
        st.sidebar.error(
            f"Could not reach the API at {api_base_url}: {exc}. Start it with "
            f"`uvicorn src.api.main:app` and check the API base URL above before running."
        )
        st.stop()

    with st.spinner("Running detection pipeline..."):
        cap = cv2.VideoCapture(video_path)
        fps = int(cap.get(cv2.CAP_PROP_FPS)) or 30
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 100

        raw_out = "temp_out.mp4"
        final_out = "final_out.mp4"
        out = cv2.VideoWriter(raw_out, cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))

        detector_kwargs = dict(
            fps=fps,
            config=CONFIG_PATH,
            conf_threshold=conf_threshold,
            min_duration_s=min_duration_frames / fps,
        )
        if st.session_state.calibration_bundle is not None:
            calibration, track_frame, boundary, heading_rad = st.session_state.calibration_bundle
            detector_kwargs.update(
                calibration=calibration, track_frame=track_frame, boundary=boundary, heading_rad=heading_rad
            )
        detector = TrackLimitDetector(**detector_kwargs)

        events = []
        progress_bar = st.progress(0)
        frame_id = 0

        # Raw (undecorated) frames, keyed by frame_id -- only kept for a
        # calibrated run, and only so build_incident_annotations' matching
        # frame_ids can be turned into real evidence clips below.
        # detector.process_frame draws directly onto its `frame` argument,
        # so the copy must happen before that call.
        raw_frames_by_id = {}

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            frame_id += 1
            if detector.calibration is not None:
                raw_frames_by_id[frame_id] = frame.copy()
            proc_frame, frame_findings = detector.process_frame(frame, frame_id)
            out.write(proc_frame)

            for event, _finding, _verdict in frame_findings:
                events.append(event)

            if frame_id % 5 == 0:
                progress_bar.progress(min(frame_id / total_frames, 1.0))

        for event, _finding, _verdict in detector.finalize(frame_id):
            events.append(event)

        cap.release()
        out.release()
        progress_bar.empty()

        # Best-effort re-encode; falls back to the raw mp4v file (still a
        # complete, readable clip) if ffmpeg isn't installed, same
        # fallback src.render.overlay.render_incident_clip uses for the
        # per-finding evidence clips below.
        final_out = try_reencode_h264(raw_out, final_out)

        # --- Evidence clips (Section 5.9), calibrated runs only ---
        # Only a calibrated run has real per-wheel contact geometry to draw
        # (src.render.incident.build_incident_annotations needs it); an
        # uncalibrated event is always INSUFFICIENT_EVIDENCE server-side
        # anyway, so there is nothing a clip would usefully show for it.
        clip_paths = {}
        if detector.calibration is not None:
            os.makedirs(EVIDENCE_CLIP_DIR, exist_ok=True)
            for event in events:
                pairs = build_incident_annotations(
                    detector._states, event, detector.track_frame, detector.heading_rad, fps
                )
                frames, annotations = [], []
                for fid, annotation in pairs:
                    raw_frame = raw_frames_by_id.get(fid)
                    if raw_frame is None:
                        continue
                    frames.append(raw_frame)
                    annotations.append(annotation)

                if not frames:
                    continue  # no captured frame overlaps this event's window -- honestly submit no clip

                clip_path = os.path.join(EVIDENCE_CLIP_DIR, f"{event.event_id}.mp4")
                try:
                    clip_paths[event.event_id] = render_incident_clip(
                        frames, annotations, event, detector.track_frame, detector.boundary,
                        detector.calibration.inverse_homography, clip_path, fps,
                    )
                except Exception:
                    # Advisory only -- a failed clip render never blocks
                    # submission of the event itself.
                    pass

        # --- Submit every candidate event to the steward console API ---
        # Tier 2 (rule evaluation), Tier 4 (trust) and Tier 3 (the agent,
        # on the ambiguous slice) all now run server-side on receipt --
        # this script's only job is getting the event there.
        results = []
        reproj_error_px = detector.calibration.reprojection_error_px if detector.calibration is not None else None
        with httpx.Client(timeout=30.0) as client:
            for event in events:
                payload = {
                    "event": asdict(event),
                    "evidence": {"reproj_error_px": reproj_error_px, "occlusion_frac": 0.0, "n_sensors": 1},
                    "evidence_clip_path": clip_paths.get(event.event_id),
                }
                try:
                    resp = client.post(f"{api_base_url}/events", json=payload)
                    resp.raise_for_status()
                    item = resp.json()
                    results.append({
                        "event_id": event.event_id,
                        "corner": event.corner,
                        "wheels_off_peak": event.wheels_off_peak,
                        "submitted": True,
                        "verdict": item["verdict"],
                        "trust_scalar": round(item["trust"]["scalar"], 2),
                        "error": None,
                    })
                except httpx.HTTPError as exc:
                    results.append({
                        "event_id": event.event_id,
                        "corner": event.corner,
                        "wheels_off_peak": event.wheels_off_peak,
                        "submitted": False,
                        "verdict": None,
                        "trust_scalar": None,
                        "error": str(exc),
                    })

        st.session_state.findings = results
        st.session_state.processed_video = final_out

# --- RESULTS ---
if st.session_state.processed_video:
    final_out = st.session_state.processed_video
    results = st.session_state.findings

    submitted = sum(1 for r in results if r["submitted"])
    failed = sum(1 for r in results if not r["submitted"])

    m1, m2, m3 = st.columns(3)
    m1.metric("Candidate Events", len(results))
    m2.metric("Submitted to Console", submitted)
    m3.metric("Failed to Submit", failed)

    st.markdown("<br>", unsafe_allow_html=True)

    col1, col2 = st.columns([1.5, 1], gap="medium")

    with col1:
        st.subheader("▶️ Output: Boundary-Overlay Replay")
        st.video(final_out)
        if st.session_state.calibration_bundle is not None:
            st.caption(
                "Boundary drawn from the calibration applied for this run — a real homography "
                "and a straight local track model, valid only near the segment calibrated."
            )
        else:
            st.caption(
                "The drawn zone is illustrative only — a fixed screen-space region, not a calibrated "
                "track boundary. Use the Calibration panel in the sidebar for real geometry."
            )

    with col2:
        st.subheader("📤 Submission Summary")
        if not results:
            st.success("✅ No candidate excursions detected in this clip.")
        else:
            st.caption(
                "Every candidate above was sent to the steward console API. "
                "Open console/ (pointed at the same API base URL) to review, "
                "confirm, or reject them — this page doesn't decide anything."
            )
            st.dataframe(
                [
                    {
                        "event_id": r["event_id"],
                        "corner": r["corner"],
                        "wheels_off_peak": r["wheels_off_peak"],
                        "verdict": r["verdict"] or "—",
                        "trust": r["trust_scalar"] if r["trust_scalar"] is not None else "—",
                        "status": "submitted" if r["submitted"] else f"FAILED: {r['error']}",
                    }
                    for r in results
                ],
                use_container_width=True,
                hide_index=True,
            )
            if failed:
                st.warning(
                    f"{failed} event(s) could not be submitted — check the API base URL in the "
                    "sidebar and that `uvicorn src.api.main:app` is running, then re-run the pipeline."
                )
else:
    st.info("👈 Load a clip and click **'Run Detection Pipeline'** in the sidebar to begin.")
