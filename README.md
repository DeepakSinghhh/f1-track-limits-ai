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

- `src/trust/components.py` (Section 5.7, Tier 4) — the five independently
  displayed trust components (`evidence_quality`, `measurement_margin`,
  `model_confidence` input, `rule_determinacy`, `precedent_consistency`),
  `combine()` into a scalar, and `decide_verdict()`: the abstention policy
  ("if scalar < threshold or the conformal set has >1 element, verdict is
  INSUFFICIENT_EVIDENCE"). This is where the plan's fuller abstain
  capability actually lives — Tier 4 can downgrade a confident Tier 2
  finding to abstention on low trust, but never invents a violation
  Tier 2 didn't find.
- `src/trust/calibrate.py` — isotonic regression (pool-adjacent-violators,
  implemented directly rather than adding scikit-learn for one function)
  turning a raw confidence into a calibrated probability, plus expected
  calibration error (ECE) so the calibration is itself measured.
- `src/trust/conformal.py` — split conformal prediction (~40 lines, per
  the plan) giving a distribution-free coverage guarantee: a singleton
  prediction set is confident, a two-element (or, when even more
  uncertain than the calibration set ever saw, empty-falling-back-to-both)
  set is genuine ambiguity.

- `src/events/localise.py` (Section 5.4, Tier 1) — `localise_events`:
  hysteresis (+2cm enter / -2cm exit) plus a minimum-duration gate over a
  `CarState` stream, no trained model. The trigger signal is the CAR's own
  margin (all telemetry has, per Section 5.2 — wheel_d is None there),
  while `wheels_off_peak` is recorded separately only where wheel data
  exists; this also matches Section 2's funnel, where most candidates
  turn out to be legal (1-3 wheels), not four-wheel violations. Proposes
  FORCED_OFF / AVOIDANCE / EXCURSION_NO_ADVANTAGE from `RelationalContext`
  (the counterfactual-gain split against EXCURSION_WITH_GAIN is Section
  5.5's estimator, not built yet). `tests/test_pipeline_localise_to_rules.py`
  proves its `ExcursionEvent` output feeds `rules/engine.py` with no
  adapter needed — the payoff of fixing data contracts before any tier.

- `src/api/main.py` (Section 5.10, Tier 5 backend) — FastAPI + WebSocket
  serving a ranked steward review queue: `POST /events` runs an
  `ExcursionEvent` through `RuleEngine` and `trust/`, builds a
  `StewardItem`, and broadcasts it; `GET /queue` returns items sorted by
  `priority` (the trust scalar); `POST /queue/{id}/confirm` and
  `/reject` are the only path to `EscalationEngine.increment_strike` /
  `reject_finding` — routed through a steward decision, exactly like
  `app.py`. `GET /overrides` exposes the audit log; `/ws/queue` pushes a
  snapshot on connect and a broadcast on every new item. Two honest gaps
  stated in its own module docstring: `agent_reasoning` and
  `evidence_clip_path` are always `None` (Tiers 3 and 5's clip export
  aren't built), and `conformal_set` is always a singleton matching the
  rule engine's own verdict, because real conformal prediction needs a
  calibration set `src/eval/` doesn't produce yet — the API doesn't
  fabricate an ambiguity signal it has no data to support.

Run the tests: `pip install -r requirements.txt && python3 -m pytest`
(99 tests, including the five Section 5.6 requires verbatim and the
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

- `src/telemetry/`, `src/vision/` (Tier 0) — perception. Nothing yet
  produces a real `CarState` stream, a real `TrackFrame`/`Boundary`, or a
  real `corner_of`/`lap_of` mapping — `events/localise.py` and
  `track/build.py` are exercised with synthetic data in tests.
  `model_confidence` in `trust/` is likewise a caller-supplied score in
  tests — nothing produces one from real data yet.
- `src/agent/` (Tier 3) — the both-sides LLM reasoning pass over the
  ambiguous slice.
- `src/render/`, `console/` (Tier 5) — the boundary-overlay clip export,
  and a real frontend for `src/api/`'s queue (`app.py`'s Streamlit UI is
  the only steward-facing surface right now, and it doesn't talk to the
  API — it evaluates and reviews findings directly, in-process).
- `src/eval/` — FIA decision scraping and metrics.

## The CV demo pipeline (`app.py`, `src/detector.py`, `src/geofence.py`)

Originally a self-contained hackathon demo that violated most of Section
0/8 directly: it auto-applied strikes and a "5s PENALTY" from a bare
frame counter, displayed a hardcoded fake confidence ("94.2%") and a
fabricated trajectory chart, and had UI controls (a circuit dropdown, a
confidence slider, a debounce slider) that did nothing. It has been
rewired onto the real core above rather than patched in place:

- `src/geofence.py`'s `ZoneCrossingTracker` replaced the auto-striking
  `TrackLimitTracker` — it only turns a per-frame zone-crossing boolean
  into a candidate `ExcursionEvent` (hysteresis + duration gate, same
  shape as `events/localise.py`), and touches no strike state. The dead,
  unused `GeofenceEngine` class (a hardcoded polygon nothing called) was
  deleted.
- `src/detector.py` now loads a real `EventConfig`
  (`config/events/demo_clip.yaml`) and runs every candidate event through
  the actual `RuleEngine`. It also fixed a real bug: the old code called
  `tracker.update()` once per detected box per frame into one shared
  tracker, so multiple vehicles in frame corrupted each other's state;
  the confidence-threshold slider was wired up but never read.
- Because this pipeline detects one reference point per vehicle (a
  bounding-box bottom-centre), not per-wheel contact patches — exactly
  what Section 5.3 calls "indefensible under questioning" — every
  candidate event honestly carries `wheels_off_peak = None`. The same
  `RuleEngine` that handles this everywhere else correctly reports
  `INSUFFICIENT_EVIDENCE` for it, rather than the pipeline asserting a
  violation it has no contact-patch evidence for.
- `app.py` no longer shows any fabricated number. It runs detection into
  a steward review queue — each candidate event shows its real citations
  and `exceptions_evaluated` — and strikes move only when a steward clicks
  **Confirm Violation**, via `EscalationEngine.increment_strike` and
  `OverrideLog`, exactly as everywhere else in this project. The sidebar
  states the pipeline's real limitations (illustrative zone, no contact
  patches) instead of implying calibrated precision it doesn't have.
  `tests/test_pipeline_demo_to_rules.py` checks the abstain behavior
  end-to-end.

`src/kinematics.py` and `src/calibration.py` were already dead code (never
imported by `app.py` or `src/detector.py`) before this pass and remain so
— left alone rather than wired in, since making them load-bearing would
mean building the real per-clip calibration flow Section 5.3 describes
(an interactive 4-point tool), not hardcoding one clip's homography as if
it applied to any uploaded video.
