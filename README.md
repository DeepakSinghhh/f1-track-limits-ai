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
  snapshot on connect and a broadcast on every new item. `conformal_set`
  is still always a singleton matching the rule engine's own verdict —
  real conformal prediction needs a calibration set `src/eval/` doesn't
  produce yet, and the API doesn't fabricate an ambiguity signal it has
  no data to support.
  **`agent_reasoning` is now wired in** (Section 5.8, Tier 3): `create_app`
  takes an optional `agent_client` (a Groq client; `None` by default, so
  the API works exactly as before with no key or network configured).
  When one is supplied, any submitted item whose trust scalar falls below
  0.5 — the same threshold `decide_verdict` uses to abstain, so this is
  literally "the ambiguous slice" — gets a real
  `reason_about_finding` call, formatted into `agent_reasoning` using
  Section 5.8's own template (`FINDING:` / `CASE FOR VIOLATION:` /
  `CASE AGAINST:` / `MISSING EVIDENCE:` / `PRECEDENTS THIS SESSION:` /
  `RECOMMENDATION:`) verbatim. The call runs via `asyncio.to_thread` so a
  slow synchronous Groq call doesn't block the event loop, and any
  failure (network, a malformed response) is caught and leaves
  `agent_reasoning` at `None` rather than failing the submission — the
  agent is advisory, so its absence is just the same as not configuring
  one. Confirmed with 5 new API tests (agent triggered under low trust,
  skipped under high trust, failure isolation, and the disabled-by-default
  case) using the same scripted fake Groq client as `src/agent/`'s own
  tests (now shared from `tests/fake_groq.py` instead of duplicated).
  CORS is enabled (`allow_origins=["*"]`, permissive by design for a local
  demo API with no auth of its own) specifically so `console/` — running
  on a different dev port — can reach it.

- `src/review_queue.py` (Tiers 3+4, shared) — `app.py` now runs the same
  trust + agent computation as `src/api/main.py`, factored out here since
  `app.py` annotates a whole clip's findings in one batch rather than one
  HTTP request at a time. `annotate_findings` takes the
  `(ExcursionEvent, Finding, Verdict)` triples `TrackLimitDetector` now
  returns (previously just `(Finding, Verdict)` — extending that tuple
  was the one breaking API change here, since `measurement_margin` and
  `rule_determinacy` both need the event, not just the finding, and
  `app.py` had never computed trust at all before this) and returns a
  `TrustVector` plus a Tier-4 `display_verdict` per finding, exactly the
  way `decide_verdict` downgrades Tier 2's own verdict to
  `INSUFFICIENT_EVIDENCE` on low trust and never upgrades one into a
  violation Tier 2 didn't find. The Tier 3 agent runs on whatever lands
  below the same 0.5 threshold, using the same `format_agent_reasoning`
  template (now a single shared function in `src/agent/reason.py` instead
  of duplicated in `src/api/main.py`). `app.py`'s sidebar constructs a
  `groq.Groq` client from `GROQ_API_KEY` if the environment has one and
  says plainly whether the agent is enabled; with no key, trust bars and
  the Tier 4 abstention decision still run, only the agent step is
  skipped, matching the API's own optional wiring. Every finding card
  keeps the evidence-before-verdict order from Section 5.10 that
  `console/` established: description/authority/exceptions, then the
  five trust bars, then the agent's both-sides reasoning if present, then
  the verdict last — and when Tier 4 downgrades Tier 2's own verdict, the
  card says so explicitly rather than just quietly showing the milder
  one. 6 new tests (`tests/test_review_queue.py`) cover high-trust
  pass-through, low-trust downgrade + agent trigger, no-agent-configured,
  agent-failure isolation, and that precedent consistency accumulates
  per corner in submission order — all against synthetic findings, no
  Streamlit/YOLO/network needed. Verified for real, not just unit-tested:
  `streamlit run app.py` was started and loaded in a headless browser —
  boots clean, no exception banner, and the new "Tier 3 agent:
  disabled/enabled" sidebar caption renders correctly. Running the
  detection pipeline itself (the part that needs `ultralytics` + YOLO
  weights) still can't be exercised in this sandbox — same limitation as
  every other CV-pipeline change in this project — so the trust/agent
  wiring inside that code path is verified via `src/review_queue.py`'s
  own tests, not an end-to-end pipeline run.

- `console/` (Section 5.10, Tier 5 frontend) — a real React + Vite (plain
  JS) steward console for `src/api/main.py`, not a mock. `src/api.js` is
  the only module that talks to the backend (REST + the `/ws/queue`
  WebSocket for live updates); `App.jsx` wires queue state, the
  steward id/session type toolbar, and a per-corner drift banner
  together. `StewardItemCard.jsx` follows Section 5.10 literally:
  evidence (measurements, the Tier 2 description + authority,
  exceptions evaluated, an honestly-labelled clip placeholder since no
  clip storage exists yet) renders before `TrustBars.jsx`'s five
  separate bars, which render before the Tier 3 agent's both-sides
  reasoning (if present), which renders before **the verdict badge,
  last** — "showing the conclusion first anchors the steward and
  destroys the independence that makes human review valuable," quoted
  directly from the plan. `DriftIndicator.jsx` computes a per-corner
  steward-override rate client-side from `GET /overrides` — a signal
  that a corner's config or boundary geometry may be off, not a ruling
  on any one finding. `ReviewControls.jsx` is the only path to
  Confirm/Reject, and disappears once a steward has decided.

  Verified for real, not just built: `npm run build` and `npm run lint`
  (Oxlint) both pass clean, and the whole thing was smoke-tested end to
  end against a live `uvicorn` instance in a headless browser — queue
  load over REST, a finding submitted via `POST /events` while the page
  was open appearing live over the WebSocket with no reload, and a full
  Confirm click that correctly updated both the item's decided state and
  the drift banner. (Caught one real bug doing this: `requirements.txt`
  listed bare `uvicorn`, which has no WebSocket backend on its own —
  `/ws/queue` 404'd with "No supported WebSocket library detected"
  until `websockets` was added to `requirements.txt` directly.)

- `src/eval/metrics.py` (Section 5.11) — `precision_recall` (recall is the
  metric that matters most here: "a missed violation is worse than a
  queued false positive"), `steward_agreement_by_trust_band`,
  `risk_coverage_curve`, `human_review_reduction`, `mean_flag_latency`
  ("no real-time claims without a measured latency number", Section 8).
  Every function takes plain lists rather than a specific labelled-data
  type, so all of it is usable — and tested — without
  `src/eval/scrape_fia.py` (real FIA stewards' decisions) existing yet.
  Expected calibration error already lives in `trust/calibrate.py`.

- `src/render/overlay.py` (Section 5.9) — the boundary-overlay replay clip
  export named explicitly in the problem statement. Per frame:
  `project_boundary_edge` samples `Boundary.half_width` over an s-window
  and projects it through a per-clip homography (`apply_homography`);
  `draw_contact_points` colours each tracked point by
  `wheel_margins`' sign; `draw_margin_readout` shows the minimum wheel
  margin with its uncertainty; `draw_minimap_inset` renders a bird's-eye
  (s, d) view with the car's trail in the same coordinate system as
  `track/`; `draw_timeline_strip` marks onset/peak/re-entry against the
  current playhead. `render_incident_clip` orchestrates all of it over a
  frame sequence and writes an mp4. The ffmpeg re-encode to a more
  broadly compatible codec is best-effort (`_try_reencode_h264` falls
  back to the raw `mp4v` output on a missing binary or a failed run) —
  verified in this environment, which has no system ffmpeg, that
  OpenCV's own mp4v container is a complete, independently readable clip
  either way. Caught a real bug while writing its test: an early version
  could produce `raw_path == output_path`, which would have pointed the
  re-encode step at reading and writing the same file.

- `src/agent/` (Section 5.8, Tier 3) — the LLM reasoning pass over the
  ambiguous slice (~120 items/race, never raw frames). `tools.py` exposes
  the five read-only tools (`get_telemetry`, `get_neighbouring_cars`,
  `get_session_precedents`, `get_event_notes`,
  `get_driving_standards_guideline`) as raw schemas + a dispatch table,
  bound per reasoning pass to an `AgentContext`. `precedent.py` is a
  within-session nearest-neighbour store over a plain feature vector — no
  training, no vector DB, just Euclidean distance over a handful of
  floats. `reason.py` runs a two-phase call: an ordinary tool-use loop for
  research, then one final call with no tools but a required JSON
  response covering all six mandatory template fields (finding, case for,
  case against, missing evidence, precedents, recommendation) — "this
  template is a safety control, not a formatting preference." A response
  that doesn't parse raises `MalformedAgentOutput` rather than silently
  downgrading to a guessed verdict.

  **Provider: Groq** (project choice, not the "Claude via API" the plan
  text names) via its OpenAI-compatible chat-completions API — model
  `llama-3.3-70b-versatile`, unverified against Groq's current catalog
  (see the module docstring). Two real differences from an
  Anthropic-shaped implementation, both handled explicitly rather than
  papered over: tool call arguments arrive as a JSON *string*
  (`json.loads`-ed per call, with malformed JSON caught and reported back
  to the model rather than crashing the loop), and Groq's
  `response_format={"type": "json_object"}` guarantees valid JSON but not
  which keys are present — so the mandatory-template guarantee is
  enforced by strict client-side validation after the call instead of a
  server-side schema.

  Validated two ways: 27 tests against a scripted fake client covering
  tool dispatch, tool argument parsing, tool errors, the iteration cap,
  and every malformed-output path, with no network calls — writing them
  caught a real aliasing bug: `reason_about_finding` was mutating one
  shared `messages` list throughout, so any earlier API call's recorded
  arguments would appear (to a test, or a real logging/audit consumer)
  mutated by everything that happened *after* that call — fixed by
  passing a snapshot copy into every `create()` call. Plus one real
  end-to-end call in `tests/test_agent_live.py`, skipped automatically
  without `GROQ_API_KEY`. Unlike the Anthropic version this replaced,
  that call could not be run even once from this sandbox — `api.groq.com`
  is blocked by the environment's egress policy (confirmed directly: a
  bare `curl` to it gets the same proxy rejection as the blocked
  `fia.com`/`ergast.com` hosts elsewhere in this README) — so only the
  skip path itself is confirmed, not a real pass. Needs to be run with a
  reachable network and a funded key before this is trusted in
  production.

Run the tests: `pip install -r requirements.txt && python3 -m pytest`
(204 tests + 1 skipped without an API key, including the five Section 5.6
requires verbatim and the Section 5.1 round-trip acceptance criterion).
`console/` has its own toolchain — see `console/README.md` for how to run
it against a live API.

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

- `src/telemetry/` (Tier 0, FastF1) — nothing produces a real telemetry
  `CarState` stream; the telemetry branch in the architecture diagram
  remains synthetic-data-only.
- `src/vision/` now exists as its own package (below) with Section 5.3's
  proposed `calibrate.py`/`detect.py`/`contact.py`/`project.py` layout.
  Still true: single-vehicle tracking (no ByteTrack/persistent IDs), a
  numeric calibration form rather than an interactive click tool, and
  `model_confidence` in `trust/` is still a caller-supplied score —
  nothing produces one from real data yet.
- `src/agent/` is now wired into both steward-facing surfaces — `src/api/`
  directly, `app.py` via the shared `src/review_queue.py` (above).
- `console/` is now built (above) and is the real frontend for
  `src/api/`'s queue. `app.py`'s Streamlit UI remains a separate,
  older surface that doesn't talk to the API — it evaluates and reviews
  findings directly, in-process — and still needs reconciling with (or
  retiring in favour of) `console/`. `src/render/overlay.py` is now
  wired into `app.py` (below, `src/render/incident.py`) for calibrated
  runs, but still not into `src/api/` — `console/`'s clip placeholder
  stays honest ("not attached") until a finding submitted over HTTP
  carries one.
- `src/eval/scrape_fia.py` — parsing real FIA stewards' decision documents
  into ground truth. `src/eval/metrics.py` (above) is built and tested,
  just with no real labelled data to run it against yet.

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
- Without calibration, this pipeline detects one reference point per
  vehicle (a bounding-box bottom-centre), not per-wheel contact patches —
  exactly what Section 5.3 calls "indefensible under questioning" — so
  every candidate event honestly carries `wheels_off_peak = None` and the
  `RuleEngine` correctly reports `INSUFFICIENT_EVIDENCE`, rather than the
  pipeline asserting a violation it has no contact-patch evidence for.
- **With calibration, this is no longer permanent.** `src/vision/calibrate.py`
  fits a real homography from operator-supplied point correspondences
  (`cv2.findHomography`, no hardcoded clip-specific matrix);
  `src/vision/contact.py` turns one tracked point into four real wheel
  positions from car centre + heading (`wheel_world_positions`) and each
  one's signed distance to the boundary (`wheel_margins`); `track/build.py`'s
  `build_straight_segment_track` gives a calibrated clip a real
  `TrackFrame`/`Boundary` (a straight local model, valid near the
  calibrated segment only — reusing the same classes the rest of the
  project uses, not a parallel implementation). `src/detector.py` feeds
  the resulting `CarState`s (real `s`, `d`, and `wheel_d`) straight into
  the actual `events.localise.localise_events` and `RuleEngine.evaluate`
  — the same Tier 1/2 pipeline everywhere else, not a demo-only
  reimplementation. `app.py`'s sidebar has a calibration form (point
  correspondences read off the clip's first frame, plus the two points
  defining the local track segment); once applied, findings can be real
  `VIOLATION`s, not just abstention. Without it, the pipeline falls back
  to the original single-point/zone behaviour above, unchanged.
  `tests/test_detector_calibrated.py` proves both outcomes (a genuine
  4-wheel violation and a genuine 2-wheels-legal no-violation) through
  the real pipeline, not a mock.
- `app.py` no longer shows any fabricated number in either mode. Strikes
  move only when a steward clicks **Confirm Violation**, via
  `EscalationEngine.increment_strike` and `OverrideLog`, exactly as
  everywhere else in this project.

Writing `build_straight_segment_track`'s tests caught a real geometry bug:
the fabricated closed loop's "return path" (TrackFrame needs one) was
offset by a 5cm hairline, which silently won the nearest-segment search —
flipping both sign and arc-length position — for any query more than
2.5cm off the centreline, i.e. almost every real point. Fixed by offsetting
the return path by 500m instead, comfortably past any realistic track
half-width. See the regression test and the comment at
`track/build.py`'s `_SLIVER_WIDTH_M`.

**`src/vision/` now exists as Section 5.3's proposed package**
(`calibrate.py`, `contact.py`, `project.py`, `detect.py`):
`calibrate.py` and `contact.py` are exactly the modules described just
above, moved out of the top-level `src/calibration.py`/`src/kinematics.py`
they used to be (deleted, not kept as re-export shims — every importer,
`app.py` and `src/detector.py` included, points at the new location
directly). `project.py` holds `apply_homography`/`project_boundary_edge`
(world geometry projected into image space), moved out of
`src/render/overlay.py`, which now imports them back rather than defining
them — used by both the live detector overlay and the replay clip
export, not duplicated between the two. `detect.py` is new, not just
moved: it extracts the YOLO vehicle-filtering logic that used to be two
separate, subtly-duplicated inline loops inside `src/detector.py`
(`_best_detection` for the calibrated path, an unnamed loop for the
uncalibrated one) into `iter_vehicle_detections`/`best_vehicle_detection`,
sharing one implementation, plus `load_yolo_model` for the same deferred
`ultralytics` import `src/detector.py` used to do inline. This is also
the first time that filtering logic has had direct test coverage
(`tests/test_vision_detect.py`, 7 tests against a tiny fake `results.boxes`
object) — previously it was only reachable through a full YOLO run, which
nothing in this sandbox can do. `src/detector.py`'s public behaviour is
unchanged by any of this — its return type grew from `(Finding,
Verdict)` to `(ExcursionEvent, Finding, Verdict)` per finding in the
previous change (`src/review_queue.py`'s trust computation, above), not
this one.

Still true: single dominant-vehicle tracking (no per-car ID/ByteTrack),
and `calibrate.py`'s spec describes an *interactive* click-to-pick tool;
`app.py`'s form is numeric entry against a still-frame preview, not a
click canvas.

**Evidence clips (Section 5.9) are now real for calibrated runs.**
`src/render/incident.py`'s `build_incident_annotations` is the missing
piece between a live pipeline run and `render_incident_clip`, which
previously only had synthetic test inputs: given the `CarState`s a run
already captured, it recovers each one's `frame_id` from
`session_time = frame_id / fps` (an exact round-trip, not a guess),
filters to whichever states fall inside `[event.t_onset, event.t_reentry]`,
and rebuilds each one's four wheel world positions
(`src.vision.contact.wheel_world_positions`) into a `FrameAnnotation`.
`app.py` keeps a raw (undecorated) copy of every frame while a calibrated
run is in progress — `detector.process_frame` draws directly onto its
argument, so the copy has to happen first — and after the trust/agent
pass, calls `render_incident_clip` per finding with whichever raw frames
match that event's window, writing to `data/clips/<event_id>.mp4`
(already `.gitignore`d, alongside `data/overrides/`). A finding whose
window has no matching captured frame (or whose render fails for any
reason) just shows "Evidence clip not available" rather than blocking
the rest of the queue — same advisory-only failure isolation as
everywhere else in this project. Uncalibrated runs skip this entirely:
every uncalibrated finding is `INSUFFICIENT_EVIDENCE` already, so there's
no per-wheel geometry a clip could usefully draw.

`src/api/` still doesn't produce clips — it evaluates one `ExcursionEvent`
per HTTP request with no raw frames attached at all, so there's nothing
for `render_incident_clip` to draw from on that path yet.
`build_incident_annotations` is covered by 5 new tests
(`tests/test_render_incident.py`) against synthetic `CarState`s — no
video, no YOLO, no Streamlit needed. The `app.py` wiring itself was
verified by booting `streamlit run app.py` in a headless browser after
the change (clean, no exception banner); actually producing a clip
still needs a real pipeline run, which needs `ultralytics` + YOLO
weights unavailable in this sandbox — the same standing limitation as
every other CV-pipeline change in this project.
