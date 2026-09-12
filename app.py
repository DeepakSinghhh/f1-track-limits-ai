import math

import streamlit as st
import cv2
import groq
import pandas as pd
import tempfile
import os
import subprocess

from src.agent.tools import AgentContext
from src.vision.calibrate import CalibrationError, calibrate
from src.detector import TrackLimitDetector
from src.review_queue import AGENT_TRUST_THRESHOLD, annotate_findings
from src.rules.escalation import EscalationEngine, SessionType
from src.audit.log import OverrideLog
from src.config import load_event_config
from src.track.build import build_straight_segment_track

CONFIG_PATH = "config/events/demo_clip.yaml"
OVERRIDE_LOG_PATH = "data/overrides/demo_session.jsonl"


def render_trust_bars(trust):
    """Section 5.7/5.10: five components shown separately, never
    collapsed into one opaque score.
    """
    st.caption("Trust decomposition:")
    for label, value in [
        ("Evidence quality", trust.evidence_quality),
        ("Measurement margin", trust.measurement_margin),
        ("Model confidence", trust.model_confidence),
        ("Rule determinacy", trust.rule_determinacy),
        ("Precedent consistency", trust.precedent_consistency),
    ]:
        st.progress(value, text=f"{label}: {value:.2f}")
    conformal_label = ", ".join(v.value for v in trust.conformal_set)
    ambiguous = " (ambiguous)" if len(trust.conformal_set) > 1 else ""
    st.caption(f"Scalar (ranking only): {trust.scalar:.2f} · Conformal set: {conformal_label}{ambiguous}")

st.set_page_config(page_title="Apex Assist — Steward Review Console", layout="wide")

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
    'style="color: #ff1801; margin-right: 10px;"></i>Apex Assist — Steward Review Console</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="subtitle">Decision-support demo: flags candidate track-limit excursions for human '
    'steward review, with citations and an honest verdict. It never issues a penalty or applies a '
    'strike on its own — every consequence below is the result of a steward clicking Confirm.</p>',
    unsafe_allow_html=True,
)

# --- SESSION STATE ---
if "override_log" not in st.session_state:
    st.session_state.override_log = OverrideLog(OVERRIDE_LOG_PATH)
if "escalation" not in st.session_state:
    st.session_state.escalation = EscalationEngine(load_event_config(CONFIG_PATH), st.session_state.override_log)
if "findings" not in st.session_state:
    st.session_state.findings = []
if "processed_video" not in st.session_state:
    st.session_state.processed_video = None

if "calibration_bundle" not in st.session_state:
    st.session_state.calibration_bundle = None  # (CameraCalibration, TrackFrame, Boundary, heading_rad) or None

if "agent_client" not in st.session_state:
    _groq_key = os.environ.get("GROQ_API_KEY")
    st.session_state.agent_client = groq.Groq(api_key=_groq_key) if _groq_key else None

# --- SIDEBAR: INGESTION & CONFIG ---
st.sidebar.markdown("### <i class='fa-solid fa-sliders'></i> Pipeline Ingestion", unsafe_allow_html=True)
use_sample = st.sidebar.button("⚡ Load Sample Race Clip")
uploaded_file = st.sidebar.file_uploader("📁 Ingest Custom Video", type=["mp4", "avi"])

st.sidebar.markdown("---")

with st.sidebar.expander("🎯 Calibration (optional) — real boundary & per-wheel geometry"):
    st.caption(
        "Without this, findings use the illustrative on-screen zone and always report "
        "INSUFFICIENT_EVIDENCE (no per-wheel data). With it, every point below is real: "
        "a homography fit from the correspondences you give, and a straight local track "
        "model from the two segment points — genuine VIOLATION findings become possible. "
        "Read pixel coordinates off the frame preview below once a clip is loaded."
    )

    preview_path = "sample_video.mp4" if use_sample else None
    if uploaded_file is not None:
        _preview_tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        _preview_tfile.write(uploaded_file.getvalue())
        preview_path = _preview_tfile.name
    if preview_path and os.path.exists(preview_path):
        _cap = cv2.VideoCapture(preview_path)
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
st.sidebar.markdown("### <i class='fa-solid fa-gear'></i> Session & Detection Parameters", unsafe_allow_html=True)
session_type_label = st.sidebar.selectbox("Session Type", ["Practice", "Qualifying", "Race", "Sprint"], index=2)
session_type = SessionType[session_type_label.upper()]
conf_threshold = st.sidebar.slider("YOLO Confidence Threshold", 0.3, 0.95, 0.5)
min_duration_frames = st.sidebar.slider("Minimum Event Duration (frames)", 1, 15, 4)
steward_id = st.sidebar.text_input("Steward ID", value="steward-1")

if st.session_state.agent_client is not None:
    st.sidebar.caption(
        f"**Tier 3 agent: enabled.** Findings with trust scalar below "
        f"{AGENT_TRUST_THRESHOLD} get a real Groq reasoning pass, shown "
        f"below the trust bars on that card."
    )
else:
    st.sidebar.caption(
        "**Tier 3 agent: disabled** (no `GROQ_API_KEY` in the environment). "
        "Trust bars and the Tier 4 abstention decision still run — only the "
        "agent's both-sides reasoning is skipped."
    )

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

video_path = None
if use_sample:
    video_path = "sample_video.mp4"
elif uploaded_file is not None:
    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    tfile.write(uploaded_file.read())
    video_path = tfile.name

run_clicked = st.sidebar.button("▶️ Run Detection Pipeline") if video_path else False

# --- PIPELINE EXECUTION ---
if run_clicked and video_path and os.path.exists(video_path):
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

        findings = []
        progress_bar = st.progress(0)
        frame_id = 0

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            frame_id += 1
            proc_frame, frame_findings = detector.process_frame(frame, frame_id)
            out.write(proc_frame)

            for event, finding, verdict in frame_findings:
                findings.append({"event": event, "finding": finding, "verdict": verdict, "decision": None})

            if frame_id % 5 == 0:
                progress_bar.progress(min(frame_id / total_frames, 1.0))

        for event, finding, verdict in detector.finalize(frame_id):
            findings.append({"event": event, "finding": finding, "verdict": verdict, "decision": None})

        cap.release()
        out.release()
        progress_bar.empty()

        subprocess.run(
            ["ffmpeg", "-y", "-i", raw_out, "-vcodec", "libx264", final_out],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # --- TIER 4 (trust) + TIER 3 (agent, on the ambiguous slice) ---
        # src/review_queue.annotate_findings is the same computation
        # src/api/main.py runs per POST /events, applied here in one batch
        # now that the full findings list exists.
        annotated = annotate_findings(
            [(item["event"], item["finding"], item["verdict"]) for item in findings],
            reproj_error_px=(
                detector.calibration.reprojection_error_px if detector.calibration is not None else None
            ),
            agent_context=AgentContext(config=load_event_config(CONFIG_PATH)),
            agent_client=st.session_state.agent_client,
        )
        for item, ann in zip(findings, annotated):
            item["trust"] = ann.trust
            item["display_verdict"] = ann.display_verdict
            item["agent_reasoning"] = ann.agent_reasoning

        st.session_state.findings = findings
        st.session_state.processed_video = final_out

# --- RESULTS ---
if st.session_state.processed_video:
    final_out = st.session_state.processed_video
    findings = st.session_state.findings

    pending = sum(1 for f in findings if f["decision"] is None)
    confirmed = sum(1 for f in findings if f["decision"] == "violation")
    rejected = sum(1 for f in findings if f["decision"] == "no_violation")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Candidate Events", len(findings))
    m2.metric("Pending Steward Review", pending)
    m3.metric("Confirmed Violations", confirmed)
    m4.metric("Rejected", rejected)

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
        st.subheader("📋 Steward Review Queue")
        if not findings:
            st.success("✅ No candidate excursions detected in this clip.")

        for i, item in enumerate(findings):
            finding = item["finding"]
            tier2_verdict = item["verdict"]
            trust = item["trust"]
            display_verdict = item["display_verdict"]
            with st.container(border=True):
                # Evidence first (Section 5.10): identifiers, description,
                # authority, and exceptions all come before any trust
                # signal or verdict — showing the conclusion first anchors
                # the steward and destroys the independence that makes
                # human review valuable.
                st.markdown(f"**Event `{finding.event_id[:8]}`** · session time `{finding.session_time}`")
                st.caption(finding.description)
                st.caption(f"Authority: {', '.join(finding.authority)}")
                st.caption(
                    "Exceptions evaluated: "
                    + ", ".join(f"{k}={v}" for k, v in finding.exceptions_evaluated.items())
                )

                render_trust_bars(trust)

                if item["agent_reasoning"]:
                    with st.expander("🤖 Tier 3 agent reasoning (advisory, not a verdict)"):
                        st.text(item["agent_reasoning"])

                verdict_label = display_verdict.value.replace("_", " ").upper()
                if display_verdict == tier2_verdict:
                    st.markdown(f"**Verdict: `{verdict_label}`**")
                else:
                    st.markdown(
                        f"**Verdict: `{verdict_label}`** — Tier 4 downgraded Tier 2's own "
                        f"`{tier2_verdict.value}` finding on low trust (see bars above)."
                    )

                if item["decision"] is None:
                    c1, c2 = st.columns(2)
                    if c1.button("Confirm Violation", key=f"confirm_{i}"):
                        result = st.session_state.escalation.increment_strike(
                            finding,
                            session_type,
                            steward_id=steward_id,
                            rationale="confirmed via steward review console",
                        )
                        item["decision"] = "violation"
                        st.session_state.findings[i] = item
                        st.success(
                            f"Strike {result.strikes} recorded."
                            + (" Lap time deleted." if result.lap_time_deleted else "")
                            + (" Black & white flag." if result.black_and_white_flag else "")
                            + (f" {result.penalty_seconds}s penalty." if result.penalty_seconds else "")
                        )
                        st.rerun()
                    if c2.button("Reject", key=f"reject_{i}"):
                        st.session_state.escalation.reject_finding(
                            finding,
                            steward_id=steward_id,
                            rationale="rejected via steward review console",
                        )
                        item["decision"] = "no_violation"
                        st.session_state.findings[i] = item
                        st.rerun()
                else:
                    st.info(f"Steward decision recorded: **{item['decision']}**")

        st.markdown("---")
        st.markdown("#### ⚖️ Steward Override Log")
        records = st.session_state.override_log.read_all()
        if records:
            df = pd.DataFrame(records)
            st.dataframe(df, use_container_width=True, hide_index=True)

            csv_data = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Download Steward Override Log (CSV)",
                data=csv_data,
                file_name="apex_assist_override_log.csv",
                mime="text/csv",
            )
        else:
            st.caption("No steward decisions recorded yet — confirm or reject a candidate event above.")
else:
    st.info("👈 Load a clip and click **'Run Detection Pipeline'** in the sidebar to begin.")
