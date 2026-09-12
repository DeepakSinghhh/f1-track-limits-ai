# Apex Assist

AI steward-assist system for F1 track-limits adjudication. See the full
implementation plan for the architecture, regulations, and non-negotiable
constraints (Section 0), module specs (Section 5), build order
(Section 6), and anti-goals (Section 8) this project is built against.

## What's implemented

The deterministic core described in Sections 0, 1, 4 and 5.6 of the plan —
the part of the system that is not allowed to be ML, and that everything
else (Tiers 0/1/3/4/5: perception, event localisation, the reasoning
agent, trust/calibration, the steward console) sits on top of:

- `src/schemas.py` — Tier 0-5 data contracts (`CarState`, `ExcursionEvent`,
  `Finding`, `Verdict`, `TrustVector`, `StewardItem`).
- `src/config.py` — loader for per-weekend Event Notes
  (`config/events/<circuit>_<year>.yaml`): monitored corners, escalation
  thresholds, minimum event duration gate, regulation citations.
  `src/rules/` never hardcodes a circuit name or corner number; a test
  (`tests/test_config.py`) greps for it.
- `src/rules/predicates.py` — the five pure predicates from Section 5.6:
  `left_the_track`, `corner_is_monitored`, `exception_forced_off`,
  `exception_justifiable_reason`, `exception_part_of_penalised_incident`.
  Each returns `(bool, citation_string)`. The one deliberate exception:
  `left_the_track` returns `(None, reason)` when wheel-contact data is
  missing — the sole case where Tier 2 cannot render a bool at all.
- `src/rules/engine.py` (Tier 2) — composes the predicates into a
  `Finding` + `Verdict`, recording every exception explicitly even when it
  doesn't apply, and rejecting excursions under the configured minimum
  duration as measurement artefacts rather than findings.
- `src/rules/escalation.py` (session-dependent consequences, Section 1.3)
  — strikes only ever move via `EscalationEngine.increment_strike`
  ("an explicit call made only by the console on steward confirmation —
  never by the pipeline", Section 5.6). A `Finding.violation == True`
  alone never changes state. Practice/Qualifying delete the lap;
  Race/Sprint follow the event's configured flag/penalty thresholds.
- `src/audit/log.py` — append-only JSONL override log. Every
  `increment_strike` / `reject_finding` call is recorded with steward id,
  system verdict, human decision, and rationale.
- `src/track/frame.py` (Section 5.1) — `TrackFrame`: `to_frenet(x, y) ->
  (s, d)` / `to_cartesian(s, d) -> (x, y)` over a closed-loop centreline,
  via cumulative arc length + nearest-segment projection. Round-trips to
  within 0.05m across a full lap (the plan's acceptance criterion, tested
  on a synthetic circle).
- `src/track/boundary.py` — `Boundary.half_width(s)` /
  `signed_distance_to_edge(s, d)` (positive = outside the track). Adds
  `white_line_width_m` to the painted edge, since the decision surface is
  the white line's outer edge, not the paint itself.
- `src/track/build.py` — `build_track`: bootstraps a `TrackFrame` from a
  reference centreline, then estimates `Boundary` edge widths from
  per-s percentiles of the lateral offset across a car-position envelope
  ("the field collectively paints the track surface"), smoothed
  circularly. Tested against a synthetic envelope with a known width.

Run the tests: `pip install -r requirements.txt && python3 -m pytest`
(41 tests, including the five Section 5.6 requires verbatim and the
Section 5.1 round-trip acceptance criterion).

### Where Tier 2's determinism ends on purpose

Section 5.7 puts confidence-based abstention (a marginal peak margin
relative to its measurement sigma) in the Tier 4 trust layer's
`measurement_margin` component and conformal prediction — not in the rule
engine. `left_the_track` therefore always returns a definite `True`/`False`
from the point-estimate measurement once duration and wheel-count are
known; `margin_uncertainty_cm` is carried through on `Finding` for Tier 4
to consume once it exists, but Tier 2 itself never second-guesses a
present measurement. The only Tier 2-level abstention is missing data.

## Not yet built

- `src/telemetry/`, `src/vision/`, `src/events/` (Tiers 0-1) — perception
  and event localisation. `src/track/` (the "spine" these depend on) is
  built, but nothing yet feeds it real session data — `build_track` is
  exercised with a synthetic car-position envelope in tests, and
  `ExcursionEvent`s are hand-built via `tests/factories.py` for `rules/`.
- `src/trust/` (Tier 4) — the five-component trust vector, isotonic
  calibration, and split conformal prediction that turns a `Finding` into
  a ranked, confidence-decomposed `StewardItem`.
- `src/agent/` (Tier 3) — the both-sides LLM reasoning pass over the
  ambiguous slice.
- `src/render/`, `src/api/`, `console/` (Tier 5) — boundary-overlay clip
  export and the steward console.
- `src/eval/` — FIA decision scraping and metrics.

`app.py` and `src/detector.py`/`src/geofence.py`/`src/kinematics.py`/
`src/calibration.py` are the pre-existing hackathon demo; they predate
this core layer and are not yet wired to it — in particular the demo
still auto-applies penalties and reports a fixed fake confidence number,
both explicitly on the Section 8 anti-goals list for the real system.
