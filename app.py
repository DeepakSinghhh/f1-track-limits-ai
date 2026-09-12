import streamlit as st
import cv2
import pandas as pd
import tempfile
import os
import subprocess

from src.detector import TrackLimitDetector
from src.rules.escalation import EscalationEngine, SessionType
from src.audit.log import OverrideLog
from src.config import load_event_config

CONFIG_PATH = "config/events/demo_clip.yaml"
OVERRIDE_LOG_PATH = "data/overrides/demo_session.jsonl"

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

# --- SIDEBAR: INGESTION & CONFIG ---
st.sidebar.markdown("### <i class='fa-solid fa-sliders'></i> Pipeline Ingestion", unsafe_allow_html=True)
use_sample = st.sidebar.button("⚡ Load Sample Race Clip")
uploaded_file = st.sidebar.file_uploader("📁 Ingest Custom Video", type=["mp4", "avi"])

st.sidebar.markdown("---")
st.sidebar.markdown("### <i class='fa-solid fa-gear'></i> Session & Detection Parameters", unsafe_allow_html=True)
session_type_label = st.sidebar.selectbox("Session Type", ["Practice", "Qualifying", "Race", "Sprint"], index=2)
session_type = SessionType[session_type_label.upper()]
conf_threshold = st.sidebar.slider("YOLO Confidence Threshold", 0.3, 0.95, 0.5)
min_duration_frames = st.sidebar.slider("Minimum Event Duration (frames)", 1, 15, 4)
steward_id = st.sidebar.text_input("Steward ID", value="steward-1")

st.sidebar.markdown("---")
st.sidebar.caption(
    "**Demo limitations**, stated rather than hidden: the drawn zone is an illustrative "
    "screen-space region, not a calibrated track boundary (see src/track/); detection uses a "
    "single reference point per vehicle, not per-wheel contact patches, so the rule engine "
    "correctly reports INSUFFICIENT_EVIDENCE for the Art. 33.3 wheel-count test on every "
    "candidate. Nothing here is auto-penalised or auto-struck."
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

        detector = TrackLimitDetector(
            fps=fps,
            config=CONFIG_PATH,
            conf_threshold=conf_threshold,
            min_duration_s=min_duration_frames / fps,
        )

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

            for finding, verdict in frame_findings:
                findings.append({"finding": finding, "verdict": verdict, "decision": None})

            if frame_id % 5 == 0:
                progress_bar.progress(min(frame_id / total_frames, 1.0))

        for finding, verdict in detector.finalize(frame_id):
            findings.append({"finding": finding, "verdict": verdict, "decision": None})

        cap.release()
        out.release()
        progress_bar.empty()

        subprocess.run(
            ["ffmpeg", "-y", "-i", raw_out, "-vcodec", "libx264", final_out],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

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
        st.caption(
            "The drawn zone is illustrative only — a fixed screen-space region, not a calibrated "
            "track boundary. src/track/ has the real Frenet-frame boundary model; it is not yet "
            "wired into this video pipeline."
        )

    with col2:
        st.subheader("📋 Steward Review Queue")
        if not findings:
            st.success("✅ No candidate excursions detected in this clip.")

        for i, item in enumerate(findings):
            finding = item["finding"]
            verdict = item["verdict"]
            with st.container(border=True):
                st.markdown(f"**Event `{finding.event_id[:8]}`** · session time `{finding.session_time}`")
                st.caption(finding.description)
                st.caption(f"Verdict: `{verdict.value}` · Authority: {', '.join(finding.authority)}")
                st.caption(
                    "Exceptions evaluated: "
                    + ", ".join(f"{k}={v}" for k, v in finding.exceptions_evaluated.items())
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
