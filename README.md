# Apex Assist

AI steward-assist system for F1 track-limits adjudication. See the full
implementation plan for the architecture, regulations, and non-negotiable
constraints (Section 0) this project is built against.

## What's implemented

The deterministic core described in Section 0/1/4 of the plan — the part
of the system that is not allowed to be ML, and that everything else
(vision, the reasoning agent, trust/calibration, the steward console) sits
on top of:

- `src/schemas.py` — Tier 0-5 data contracts (`CarState`, `ExcursionEvent`,
  `Finding`, `Verdict`, `TrustVector`, `StewardItem`).
- `src/config.py` — loader for per-weekend Event Notes
  (`config/events/<circuit>_<year>.yaml`): monitored corners, escalation
  thresholds, regulation citations. `src/rules/` never hardcodes a circuit
  name or corner number; a test (`tests/test_config.py`) guards this.
- `src/rules/predicates.py`, `src/rules/engine.py` (Tier 2) — the Art. 33.3
  core test (all four wheels beyond the outer white line edge) and every
  FIA Driving Standards Guidelines exception, evaluated and recorded
  explicitly even when they don't apply. Produces a `Verdict` that can be
  `INSUFFICIENT_EVIDENCE` — measurement uncertainty and missing wheel-
  contact data abstain rather than guess.
- `src/rules/escalation.py` (session-dependent consequences) — strikes
  only ever move via `EscalationEngine.confirm_violation`, called only in
  response to a steward decision. A `Finding.violation == True` alone
  never changes state.
- `src/audit/log.py` — append-only JSONL override log. Every
  `confirm_violation` / `reject_finding` call is recorded with steward id,
  system verdict, human decision, and rationale.

Run the tests: `pip install -r requirements.txt && python3 -m pytest`.

## Not yet built

Tiers 0, 1, 3, 4, 5 (perception, event localisation, the LLM reasoning
agent, trust/calibration, and the steward console) — see the plan for
their data contracts and expected throughput funnel. `app.py` and
`src/detector.py`/`src/geofence.py`/`src/kinematics.py`/
`src/calibration.py` are the pre-existing hackathon demo; they predate
this core layer and are not yet wired to it — in particular the demo
still auto-applies penalties and reports a fixed fake confidence number,
which the plan's Section 0 explicitly rules out for the real system.
