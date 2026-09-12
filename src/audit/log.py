"""Steward override log.

Apex Assist plan, Section 0: "Every steward override is logged. The
override log is a deliverable, not telemetry." Every human decision that
confirms, rejects, or overrides a system Finding is appended here —
append-only, one JSON record per line, never mutated or deleted.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class OverrideRecord:
    timestamp: str
    steward_id: str
    event_id: str
    car_number: int
    lap: int
    corner: int
    system_verdict: str          # what the rule engine (Tier 2) found
    human_decision: str          # what the steward decided: "violation" | "no_violation"
    rationale: str
    strikes_after: int | None    # None unless human_decision == "violation"


class OverrideLog:
    """Append-only JSONL log of steward decisions on Findings.

    One file per event weekend, matching the config it was decided under.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        steward_id: str,
        event_id: str,
        car_number: int,
        lap: int,
        corner: int,
        system_verdict: str,
        human_decision: str,
        rationale: str,
        strikes_after: int | None = None,
    ) -> OverrideRecord:
        entry = OverrideRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            steward_id=steward_id,
            event_id=event_id,
            car_number=car_number,
            lap=lap,
            corner=corner,
            system_verdict=system_verdict,
            human_decision=human_decision,
            rationale=rationale,
            strikes_after=strikes_after,
        )
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry)) + "\n")
        return entry

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
