import json
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from tests.factories import make_event
from tests.fake_groq import FakeClient, text_response

CONFIG_PATH = "config/events/red_bull_ring_2023.yaml"

VALID_AGENT_ANSWER = {
    "finding": "Car 44 ran wide at turn 1.",
    "case_for_violation": "Telemetry shows the car beyond the boundary for the full excursion.",
    "case_against": "No car was alongside; looks like a mistake, not exploitation.",
    "missing_evidence": "none",
    "precedents_this_session": "none retrieved",
    "recommendation": "violation",
}


@pytest.fixture
def client(tmp_path):
    app = create_app(config_path=CONFIG_PATH, override_log_path=str(tmp_path / "overrides.jsonl"))
    return TestClient(app)


def make_client_with_agent(tmp_path, responses):
    fake_agent = FakeClient(responses)
    app = create_app(
        config_path=CONFIG_PATH, override_log_path=str(tmp_path / "overrides.jsonl"), agent_client=fake_agent
    )
    return TestClient(app), fake_agent


def event_payload(**overrides):
    event = make_event(**overrides)
    return {"event": asdict(event)}


def test_cors_allows_a_browser_frontend_on_a_different_origin(client):
    resp = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert resp.headers.get("access-control-allow-origin") == "*"


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["circuit"] == "red_bull_ring"
    assert body["year"] == 2023


def test_submit_clear_violation_is_ranked_with_citations(client):
    resp = client.post("/events", json=event_payload(
        corner=1, wheels_off_peak=4, max_margin_m=0.30, margin_sigma_m=0.02, duration_s=0.62,
    ))
    assert resp.status_code == 200
    item = resp.json()
    assert item["verdict"] == "violation"
    assert item["finding"]["authority"] == ["F1SR Art. 33.3", "FIA Driving Standards Guidelines v4.1"]
    assert item["agent_reasoning"] is None
    assert item["evidence_clip_path"] is None
    assert 0.0 <= item["trust"]["scalar"] <= 1.0
    assert item["trust"]["conformal_set"] == ["violation"]


def test_submit_missing_wheel_data_is_insufficient_evidence(client):
    resp = client.post("/events", json=event_payload(corner=1, wheels_off_peak=None))
    assert resp.status_code == 200
    item = resp.json()
    assert item["verdict"] == "insufficient_evidence"
    assert item["finding"]["violation"] is False


def test_queue_is_sorted_by_priority_descending(client):
    # low measurement_margin -> lower trust scalar -> lower priority
    low = client.post("/events", json=event_payload(
        event_id="low", corner=1, wheels_off_peak=4, max_margin_m=0.02, margin_sigma_m=0.05, duration_s=0.62,
    )).json()
    high = client.post("/events", json=event_payload(
        event_id="high", corner=1, wheels_off_peak=4, max_margin_m=0.30, margin_sigma_m=0.01, duration_s=0.62,
    )).json()

    queue = client.get("/queue").json()
    assert [it["finding"]["event_id"] for it in queue] == ["high", "low"]
    assert queue[0]["priority"] >= queue[1]["priority"]


def test_get_single_item(client):
    submitted = client.post("/events", json=event_payload(event_id="evt-1", corner=1)).json()
    resp = client.get(f"/queue/{submitted['finding']['event_id']}")
    assert resp.status_code == 200
    assert resp.json()["finding"]["event_id"] == "evt-1"


def test_get_missing_item_404s(client):
    resp = client.get("/queue/does-not-exist")
    assert resp.status_code == 404


def test_confirm_increments_strike_and_writes_override_log(client):
    submitted = client.post("/events", json=event_payload(
        event_id="evt-confirm", corner=1, wheels_off_peak=4, max_margin_m=0.30, margin_sigma_m=0.02, duration_s=0.62,
    )).json()
    event_id = submitted["finding"]["event_id"]

    resp = client.post(
        f"/queue/{event_id}/confirm",
        json={"steward_id": "steward-1", "rationale": "clear overshoot", "session_type": "race"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["strikes"] == 1
    assert body["penalty_seconds"] == 0

    overrides = client.get("/overrides").json()
    assert len(overrides) == 1
    assert overrides[0]["human_decision"] == "violation"
    assert overrides[0]["strikes_after"] == 1


def test_reject_does_not_increment_strike(client):
    submitted = client.post("/events", json=event_payload(event_id="evt-reject", corner=1)).json()
    event_id = submitted["finding"]["event_id"]

    resp = client.post(f"/queue/{event_id}/reject", json={"steward_id": "steward-1"})
    assert resp.status_code == 200

    overrides = client.get("/overrides").json()
    assert overrides[0]["human_decision"] == "no_violation"
    assert overrides[0]["strikes_after"] is None


def test_double_review_is_rejected_with_409(client):
    submitted = client.post("/events", json=event_payload(event_id="evt-double", corner=1)).json()
    event_id = submitted["finding"]["event_id"]

    client.post(f"/queue/{event_id}/reject", json={"steward_id": "steward-1"})
    resp = client.post(f"/queue/{event_id}/confirm", json={"steward_id": "steward-1"})
    assert resp.status_code == 409


def test_confirm_missing_event_404s(client):
    resp = client.post("/queue/does-not-exist/confirm", json={"steward_id": "steward-1"})
    assert resp.status_code == 404


def test_confirm_unknown_session_type_422s(client):
    submitted = client.post("/events", json=event_payload(event_id="evt-bad-session", corner=1)).json()
    event_id = submitted["finding"]["event_id"]
    resp = client.post(
        f"/queue/{event_id}/confirm", json={"steward_id": "steward-1", "session_type": "endurance"}
    )
    assert resp.status_code == 422


def test_websocket_receives_snapshot_then_broadcast(client):
    client.post("/events", json=event_payload(event_id="before-connect", corner=1))

    with client.websocket_connect("/ws/queue") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert len(snapshot["items"]) == 1
        assert snapshot["items"][0]["finding"]["event_id"] == "before-connect"

        client.post("/events", json=event_payload(event_id="after-connect", corner=1))

        broadcast = ws.receive_json()
        assert broadcast["type"] == "new_item"
        assert broadcast["item"]["finding"]["event_id"] == "after-connect"


# --- Tier 3 (agent) wiring ---

def test_health_reports_whether_agent_is_enabled(client, tmp_path):
    assert client.get("/health").json()["agent_enabled"] is False

    agent_client, _ = make_client_with_agent(tmp_path, [text_response(json.dumps(VALID_AGENT_ANSWER))])
    assert agent_client.get("/health").json()["agent_enabled"] is True


def test_low_trust_item_triggers_the_agent_and_populates_reasoning(tmp_path):
    client, fake_agent = make_client_with_agent(
        tmp_path,
        [
            text_response("no tools needed"),
            text_response(json.dumps(VALID_AGENT_ANSWER)),
        ],
    )
    payload = event_payload(
        event_id="evt-low-trust", corner=1, wheels_off_peak=2, max_margin_m=0.01, margin_sigma_m=5.0
    )
    payload["evidence"] = {"model_confidence": 0.1}

    item = client.post("/events", json=payload).json()

    assert item["trust"]["scalar"] < 0.5
    assert item["agent_reasoning"] is not None
    assert "FINDING:" in item["agent_reasoning"]
    assert "CASE FOR VIOLATION:" in item["agent_reasoning"]
    assert "CASE AGAINST:" in item["agent_reasoning"]
    assert "RECOMMENDATION: violation" in item["agent_reasoning"]
    assert len(fake_agent.chat.completions.calls) == 2


def test_high_trust_item_never_calls_the_agent(tmp_path):
    client, fake_agent = make_client_with_agent(tmp_path, [text_response(json.dumps(VALID_AGENT_ANSWER))])
    payload = event_payload(
        event_id="evt-high-trust", corner=1, wheels_off_peak=4, max_margin_m=0.30, margin_sigma_m=0.02
    )

    item = client.post("/events", json=payload).json()

    assert item["trust"]["scalar"] >= 0.5
    assert item["agent_reasoning"] is None
    assert len(fake_agent.chat.completions.calls) == 0


def test_agent_failure_never_blocks_the_submission(tmp_path):
    # no scripted responses at all -- the very first call raises inside
    # the fake, standing in for a network error or a malformed response
    client, fake_agent = make_client_with_agent(tmp_path, [])
    payload = event_payload(
        event_id="evt-agent-fails", corner=1, wheels_off_peak=2, max_margin_m=0.01, margin_sigma_m=5.0
    )
    payload["evidence"] = {"model_confidence": 0.1}

    resp = client.post("/events", json=payload)

    assert resp.status_code == 200
    assert resp.json()["agent_reasoning"] is None


def test_no_agent_client_configured_means_reasoning_always_none(client):
    payload = event_payload(
        event_id="evt-no-agent", corner=1, wheels_off_peak=2, max_margin_m=0.01, margin_sigma_m=5.0
    )
    payload["evidence"] = {"model_confidence": 0.1}

    item = client.post("/events", json=payload).json()
    assert item["agent_reasoning"] is None
