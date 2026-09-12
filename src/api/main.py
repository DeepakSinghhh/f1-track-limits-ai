"""Tier 5 backend (Section 5.10): FastAPI + WebSocket serving a ranked
steward review queue built on the deterministic core above. This is what
turns Tier 2 (rules), the escalation/audit layer, and Tier 4 (trust) into
something an actual console can hit.

Tier 3 (the agent) is now wired in, but only conditionally: create_app's
agent_client is optional (None by default), so the API works exactly as
before with no API key or network configured. When a client is supplied,
the agent runs on the "ambiguous slice" -- items whose trust scalar falls
below the same threshold decide_verdict uses to abstain -- and its
both-sides reasoning is formatted into StewardItem.agent_reasoning using
Section 5.8's own template. A failed or slow agent call never blocks or
fails the finding submission itself: it's advisory, so its absence just
means agent_reasoning stays None, same as if no client were configured.

One more honest gap, stated rather than hidden: real conformal prediction
(Section 5.7) needs a calibration set of labelled outcomes, which only
exists once src/eval/scrape_fia.py is built. Until then, every item's
conformal_set is a singleton matching the rule engine's own verdict —
this API does not fabricate an ambiguity signal it has no calibration
data to support.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware

from src.agent.reason import format_agent_reasoning, reason_about_finding
from src.agent.tools import AgentContext
from src.audit.log import OverrideLog
from src.config import load_event_config
from src.rules.engine import RuleEngine
from src.rules.escalation import EscalationEngine, SessionType
from src.rules.session_state import SessionState
from src.schemas import ExcursionEvent, StewardItem, Verdict
from src.trust.components import (
    build_trust_vector,
    decide_verdict,
    evidence_quality,
    measurement_margin,
    precedent_consistency,
    rule_determinacy,
)

#: Section 5.8: the agent runs on items Tier 4 could not resolve with
#: confidence -- the same scalar_threshold decide_verdict's own default
#: uses to abstain, so "ambiguous slice" and "would otherwise abstain"
#: are the same set of items here.
AGENT_TRUST_THRESHOLD = 0.5


@dataclass
class EvidenceContext:
    """Facts the trust layer needs that ExcursionEvent doesn't carry (in
    the real pipeline these live on CarState, not the event itself).
    """

    reproj_error_px: float | None = None
    occlusion_frac: float = 0.0
    n_sensors: int = 1
    model_confidence: float = 0.5  # neutral until Tier 1/3 produce a real one


@dataclass
class EvaluateRequest:
    event: ExcursionEvent
    evidence: EvidenceContext = field(default_factory=EvidenceContext)


@dataclass
class ReviewRequest:
    steward_id: str
    rationale: str = ""
    session_type: str = "race"


class QueueBroadcaster:
    def __init__(self) -> None:
        self.connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.connections:
            self.connections.remove(websocket)

    async def broadcast(self, payload: dict) -> None:
        dead = []
        for websocket in self.connections:
            try:
                await websocket.send_json(payload)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(websocket)


def _serialize_item(item: StewardItem) -> dict:
    return jsonable_encoder(item)


def create_app(
    config_path: str = "config/events/red_bull_ring_2023.yaml",
    override_log_path: str = "data/overrides/api_session.jsonl",
    agent_client=None,
) -> FastAPI:
    app = FastAPI(title="Apex Assist Steward Console API")
    # Permissive by design: this is a local demo API with no auth of its
    # own, meant to be hit from console/ running on a different dev port.
    # Tighten allow_origins before this is ever deployed anywhere real.
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"]
    )

    config = load_event_config(config_path)
    app.state.config = config
    app.state.rule_engine = RuleEngine(config)
    app.state.override_log = OverrideLog(override_log_path)
    app.state.escalation = EscalationEngine(config, app.state.override_log)
    app.state.session_state = SessionState()
    app.state.items: dict[str, StewardItem] = {}
    app.state.decisions: dict[str, str] = {}
    app.state.broadcaster = QueueBroadcaster()
    app.state.agent_client = agent_client

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "circuit": config.circuit, "year": config.year, "agent_enabled": agent_client is not None}

    @app.post("/events")
    async def submit_event(payload: EvaluateRequest) -> StewardItem:
        event = payload.event
        evidence = payload.evidence

        finding, tier2_verdict = app.state.rule_engine.evaluate(event, app.state.session_state)

        prior_verdicts = [
            Verdict(app.state.decisions[eid])
            for eid, other in app.state.items.items()
            if eid in app.state.decisions and other.finding.corner == finding.corner
        ]

        eq = evidence_quality(evidence.reproj_error_px, evidence.occlusion_frac, evidence.n_sensors)
        mm = measurement_margin(event.max_margin_m, event.margin_sigma_m)
        rd = rule_determinacy(event, finding)
        pc = precedent_consistency(tier2_verdict, prior_verdicts)

        # No real conformal calibration set exists yet (see module
        # docstring) — a singleton matching the rule engine's own verdict
        # is the honest default rather than a fabricated ambiguity signal.
        conformal_set = [tier2_verdict]

        trust = build_trust_vector(
            evidence_quality_score=eq,
            measurement_margin_score=mm,
            model_confidence_score=evidence.model_confidence,
            rule_determinacy_score=rd,
            precedent_consistency_score=pc,
            conformal_set=conformal_set,
        )

        final_verdict = decide_verdict(tier2_verdict, trust, scalar_threshold=AGENT_TRUST_THRESHOLD)

        agent_reasoning_text = None
        if app.state.agent_client is not None and trust.scalar < AGENT_TRUST_THRESHOLD:
            try:
                agent_context = AgentContext(config=app.state.config)
                reasoning = await asyncio.to_thread(
                    reason_about_finding, app.state.agent_client, finding, agent_context
                )
                agent_reasoning_text = format_agent_reasoning(reasoning)
            except Exception:
                # Advisory only: a failed or slow agent call must never
                # block or fail the finding submission itself.
                agent_reasoning_text = None

        item = StewardItem(
            finding=finding,
            trust=trust,
            verdict=final_verdict,
            agent_reasoning=agent_reasoning_text,
            evidence_clip_path=None,
            precedents=[],
            priority=trust.scalar,
        )
        app.state.items[finding.event_id] = item
        await app.state.broadcaster.broadcast({"type": "new_item", "item": _serialize_item(item)})
        return item

    @app.get("/queue")
    def get_queue() -> list[StewardItem]:
        return sorted(app.state.items.values(), key=lambda it: it.priority, reverse=True)

    @app.get("/queue/{event_id}")
    def get_item(event_id: str) -> StewardItem:
        item = app.state.items.get(event_id)
        if item is None:
            raise HTTPException(status_code=404, detail="event not found")
        return item

    @app.post("/queue/{event_id}/confirm")
    async def confirm_item(event_id: str, review: ReviewRequest) -> dict:
        item = app.state.items.get(event_id)
        if item is None:
            raise HTTPException(status_code=404, detail="event not found")
        if event_id in app.state.decisions:
            raise HTTPException(status_code=409, detail="event already reviewed")
        try:
            session_type = SessionType(review.session_type)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"unknown session_type {review.session_type!r}")

        result = app.state.escalation.increment_strike(
            item.finding, session_type, steward_id=review.steward_id, rationale=review.rationale
        )
        app.state.decisions[event_id] = "violation"
        await app.state.broadcaster.broadcast(
            {"type": "decision", "event_id": event_id, "decision": "violation", "strikes": result.strikes}
        )
        return {
            "strikes": result.strikes,
            "lap_time_deleted": result.lap_time_deleted,
            "black_and_white_flag": result.black_and_white_flag,
            "penalty_seconds": result.penalty_seconds,
        }

    @app.post("/queue/{event_id}/reject")
    async def reject_item(event_id: str, review: ReviewRequest) -> dict:
        item = app.state.items.get(event_id)
        if item is None:
            raise HTTPException(status_code=404, detail="event not found")
        if event_id in app.state.decisions:
            raise HTTPException(status_code=409, detail="event already reviewed")

        app.state.escalation.reject_finding(item.finding, steward_id=review.steward_id, rationale=review.rationale)
        app.state.decisions[event_id] = "no_violation"
        await app.state.broadcaster.broadcast({"type": "decision", "event_id": event_id, "decision": "no_violation"})
        return {"status": "rejected"}

    @app.get("/overrides")
    def get_overrides() -> list[dict]:
        return app.state.override_log.read_all()

    @app.websocket("/ws/queue")
    async def ws_queue(websocket: WebSocket) -> None:
        await app.state.broadcaster.connect(websocket)
        try:
            snapshot = [
                _serialize_item(it)
                for it in sorted(app.state.items.values(), key=lambda i: i.priority, reverse=True)
            ]
            await websocket.send_json({"type": "snapshot", "items": snapshot})
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            app.state.broadcaster.disconnect(websocket)

    return app


app = create_app()
