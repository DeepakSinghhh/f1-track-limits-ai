import TrustBars from "./TrustBars";
import ReviewControls from "./ReviewControls";

const VERDICT_LABEL = {
  violation: "Violation",
  no_violation: "No violation",
  insufficient_evidence: "Insufficient evidence",
};

/** Section 5.10: evidence first, verdict last. The system's conclusion is
 * the last thing on the card, not the first -- showing it first anchors
 * the steward and destroys the independence that makes human review
 * valuable. Evidence, measurements, exceptions, and the agent's
 * both-sides reasoning all come before the trust bars and the verdict
 * badge.
 */
export default function StewardItemCard({ item, decision, reviewProps }) {
  const { finding, trust, verdict, agent_reasoning, evidence_clip_path } = item;

  return (
    <article className="item-card" data-decided={Boolean(decision)}>
      <header className="item-card-header">
        <div className="item-id">
          <span className="car">#{finding.car_number}</span>
          <span>{finding.event_id}</span>
          <span>lap {finding.lap}</span>
          <span>turn {finding.corner}</span>
          <span>{finding.session_time}</span>
        </div>
        <span className="priority-badge">priority {item.priority.toFixed(2)}</span>
      </header>

      <div className="item-card-body">
        <dl className="evidence-block">
          <div className="evidence-field">
            <dt>Min margin</dt>
            <dd>{finding.min_margin_cm.toFixed(1)} cm</dd>
          </div>
          <div className="evidence-field">
            <dt>Margin uncertainty</dt>
            <dd>&plusmn;{finding.margin_uncertainty_cm.toFixed(1)} cm</dd>
          </div>
          <div className="evidence-field">
            <dt>Corner monitored</dt>
            <dd>{finding.corner_monitored ? "yes" : "no"}</dd>
          </div>
          <div className="evidence-field">
            <dt>Strike context</dt>
            <dd>{finding.strike_context || "none"}</dd>
          </div>
        </dl>

        <p className="description">{finding.description}</p>

        <ul className="authority-list">
          {finding.authority.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>

        <div className="exceptions-list">
          {Object.entries(finding.exceptions_evaluated).map(([name, value]) => (
            <span className="exception-chip" data-value={value} key={name}>
              {name.replaceAll("_", " ")}: {value ? "yes" : "no"}
            </span>
          ))}
        </div>

        <div className="clip-placeholder">
          {evidence_clip_path ? evidence_clip_path : "Evidence clip not attached to this finding."}
        </div>

        <TrustBars trust={trust} />

        {agent_reasoning && (
          <div className="agent-reasoning">
            <div className="agent-reasoning-title">Tier 3 agent reasoning (advisory, not a verdict)</div>
            <pre>{agent_reasoning}</pre>
          </div>
        )}

        <div className="verdict-row">
          <span className="verdict-badge" data-verdict={verdict}>
            {VERDICT_LABEL[verdict] ?? verdict}
          </span>
          {decision && <span className="decided-tag">steward decision: {decision.replaceAll("_", " ")}</span>}
        </div>
      </div>

      {!decision && <ReviewControls eventId={finding.event_id} {...reviewProps} />}
    </article>
  );
}
