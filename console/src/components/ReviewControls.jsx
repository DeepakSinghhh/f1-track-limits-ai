import { useState } from "react";

/** Confirm -> increment_strike() server-side. Reject -> no strike.
 * Every decision is logged whether it agrees with the system or not
 * (Section 0: every override is logged, not just disagreements).
 */
export default function ReviewControls({ eventId, stewardId, sessionType, onConfirm, onReject }) {
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const run = async (action) => {
    setError(null);
    setBusy(true);
    try {
      if (action === "confirm") {
        await onConfirm(eventId, { stewardId, sessionType, rationale });
      } else {
        await onReject(eventId, { stewardId, rationale });
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="review-controls">
      <textarea
        placeholder="Rationale (optional, recorded in the override log)"
        value={rationale}
        onChange={(e) => setRationale(e.target.value)}
        disabled={busy}
      />
      <div className="review-buttons">
        <button className="btn btn-confirm" disabled={busy || !stewardId} onClick={() => run("confirm")}>
          Confirm violation
        </button>
        <button className="btn btn-reject" disabled={busy || !stewardId} onClick={() => run("reject")}>
          Reject
        </button>
      </div>
      {!stewardId && <div className="review-error">Set a steward ID above to review.</div>}
      {error && <div className="review-error">{error}</div>}
    </div>
  );
}
