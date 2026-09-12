# Apex Assist Steward Console

The Tier 5 (Section 5.10) frontend for the steward review queue served by
`src/api/main.py`. Plain React + Vite (JavaScript, no TypeScript) talking
to the API over REST + a `/ws/queue` WebSocket for live updates.

## Design rule this console enforces

Section 5.10 is explicit: **evidence before verdict.** Showing the
system's conclusion first anchors the steward and destroys the
independence that makes human review valuable. Every `StewardItemCard`
renders, in this fixed order:

1. Measurements (margin, uncertainty, corner-monitored flag)
2. The Tier 2 finding description and its cited authority
3. Exceptions the rule engine evaluated (forced off, avoidance, etc.)
4. Evidence clip field (shows `evidence_clip_path` when the submitting
   pipeline rendered one, honestly labelled "not attached" when it
   didn't — still shown as text either way, not a video player)
5. The five-component trust decomposition (`TrustBars`) — never a single
   opaque score
6. The Tier 3 agent's both-sides reasoning, if the agent ran and is
   configured
7. **The verdict badge, last**
8. Confirm / Reject controls, which disappear once a steward has decided

## What's here

- `src/api.js` — the only place that talks to the backend: `fetchQueue`,
  `fetchOverrides`, `confirmItem`/`rejectItem`, and
  `connectQueueSocket()` for `/ws/queue`. The API base URL is stored in
  `localStorage` (editable from the toolbar) and defaults to
  `VITE_API_BASE_URL` or `http://localhost:8000`.
- `src/App.jsx` — queue state, WebSocket wiring (snapshot / new_item /
  decision frames), steward id + session type toolbar, and the
  per-corner drift banner.
- `src/components/StewardItemCard.jsx` — the evidence-first card
  described above.
- `src/components/TrustBars.jsx` — five bars, not one number.
- `src/components/DriftIndicator.jsx` — computes a per-corner
  override-rate from `/overrides` client-side (how often stewards have
  overturned this system's verdict at a given corner). A signal that a
  corner's config or boundary geometry may be wrong — not itself a
  ruling on any one finding.
- `src/components/ReviewControls.jsx` — Confirm (→ `increment_strike()`
  server-side) / Reject (→ no strike), both logged to the append-only
  override log regardless of which way the steward decided.

## Running it

```bash
# from the repo root, in one terminal:
uvicorn src.api.main:app --port 8000

# in another terminal:
cd console
npm install
npm run dev
```

By default the console points at `http://localhost:8000`. Override with
`VITE_API_BASE_URL` at build time, or type a different URL into the "API
base URL" field in the toolbar at runtime.

Nothing appears in the queue on its own — `console/` only reviews
findings, it can't ingest a video. Run `streamlit run app.py` (repo
root) against the same API to actually submit candidate events from a
clip; `app.py`'s own sidebar has a matching "API base URL" field so both
point at the same backend.

`npm run build` produces a static `dist/` bundle; `npm run lint` runs
Oxlint. Both are verified clean as of this commit — the app was also
smoke-tested end to end against a live `uvicorn` instance (queue load,
live WebSocket broadcast of a newly submitted finding, and a full
confirm flow that correctly updates the drift banner).

## Known gaps

- No auth. The API has none either — this is a local/demo console, not
  a deployed one. CORS on the API is wide open (`allow_origins=["*"]`)
  for the same reason.
- No evidence clip playback — `app.py` can populate `evidence_clip_path`
  now, but it's a local filesystem path with no static-file route
  serving it over HTTP, so the card still shows it as plain text rather
  than rendering a player that would likely be broken for whoever's
  actually viewing `console/`.
- The drift indicator is computed from whatever `/overrides` currently
  holds in memory for this API process; it is not persisted across
  server restarts (neither is the queue itself — `app.state.items` is
  in-memory, matching the rest of the API's current scope).
