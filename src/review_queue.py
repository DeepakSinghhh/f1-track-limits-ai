"""Shared Tier 4 (trust) + Tier 3 (agent) annotation pass over a batch of
Tier 2 findings.

src/api/main.py evaluates findings one at a time as they arrive over
HTTP, so its trust/agent wiring lives inline in the request handler.
app.py instead runs a whole clip and gets a full batch of findings back
from TrackLimitDetector at once -- this module is that same Section
5.7/5.8 computation, factored out so it's importable and testable
without Streamlit, ultralytics, or a video file anywhere in the loop.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from src.agent.reason import format_agent_reasoning, reason_about_finding
from src.agent.tools import AgentContext
from src.schemas import ExcursionEvent, Finding, TrustVector, Verdict
from src.trust.components import (
    build_trust_vector,
    decide_verdict,
    evidence_quality,
    measurement_margin,
    precedent_consistency,
    rule_determinacy,
)

#: Section 5.8: the same threshold src/api/main.py uses -- both the Tier 4
#: abstention policy and "is this item ambiguous enough to send to the
#: Tier 3 agent" share one number on purpose.
AGENT_TRUST_THRESHOLD = 0.5


@dataclass
class AnnotatedFinding:
    event: ExcursionEvent
    finding: Finding
    verdict: Verdict             # Tier 2's own verdict, never mutated
    trust: TrustVector
    display_verdict: Verdict     # verdict a steward should be shown -- Tier 2's verdict,
                                  # downgraded to INSUFFICIENT_EVIDENCE by Tier 4 on low trust,
                                  # never upgraded into a violation Tier 2 didn't find
    agent_reasoning: str | None  # Tier 3's both-sides reasoning, or None if not run/failed


def annotate_findings(
    findings: list[tuple[ExcursionEvent, Finding, Verdict]],
    *,
    reproj_error_px: float | None,
    agent_context: AgentContext,
    agent_client=None,
    scalar_threshold: float = AGENT_TRUST_THRESHOLD,
) -> list[AnnotatedFinding]:
    """Attach a Tier 4 trust vector to every finding, in order, and run
    the Tier 3 agent on whichever ones land below `scalar_threshold` --
    only when `agent_client` is given (None means the agent is skipped
    everywhere, matching src/api/main.py's own optional wiring).

    Precedent consistency accumulates per corner as findings are
    processed in the given order, exactly like src/api/main.py's own
    prior_verdicts filter over previously submitted items.
    """
    prior_verdicts_by_corner: dict[int, list[Verdict]] = defaultdict(list)
    annotated: list[AnnotatedFinding] = []

    for event, finding, verdict in findings:
        eq = evidence_quality(reproj_error_px, occlusion_frac=0.0, n_sensors=1)
        mm = measurement_margin(event.max_margin_m, event.margin_sigma_m)
        rd = rule_determinacy(event, finding)
        pc = precedent_consistency(verdict, prior_verdicts_by_corner[finding.corner])

        trust = build_trust_vector(
            evidence_quality_score=eq,
            measurement_margin_score=mm,
            model_confidence_score=0.5,  # neutral -- no real model-confidence estimator yet
            rule_determinacy_score=rd,
            precedent_consistency_score=pc,
            conformal_set=[verdict],  # singleton stub -- no calibration set yet, see README
        )
        prior_verdicts_by_corner[finding.corner].append(verdict)

        display_verdict = decide_verdict(verdict, trust, scalar_threshold=scalar_threshold)

        agent_reasoning = None
        if agent_client is not None and trust.scalar < scalar_threshold:
            try:
                reasoning = reason_about_finding(agent_client, finding, agent_context)
                agent_reasoning = format_agent_reasoning(reasoning)
            except Exception:
                # Advisory only -- a failed or slow agent call never blocks
                # the rest of the batch, matching src/api/main.py.
                agent_reasoning = None

        annotated.append(
            AnnotatedFinding(
                event=event,
                finding=finding,
                verdict=verdict,
                trust=trust,
                display_verdict=display_verdict,
                agent_reasoning=agent_reasoning,
            )
        )

    return annotated
