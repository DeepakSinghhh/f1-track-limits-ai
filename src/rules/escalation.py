"""Session-dependent consequence engine (Apex Assist plan, Section 1.3).

Strike counts and consequences here are all downstream of a human steward
confirming a Finding — never of the Finding alone. Calling
EscalationEngine.confirm_violation is itself the auditable steward action;
the caller (Tier 5 console) must not invoke it except in direct response
to a steward's decision, and every call is written to the OverrideLog.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.audit.log import OverrideLog
from src.config import EventConfig
from src.schemas import Finding


class SessionType(str, Enum):
    PRACTICE = "practice"
    QUALIFYING = "qualifying"
    RACE = "race"
    SPRINT = "sprint"


#: Practice/Qualifying: Section 1.3 — lap time deleted, effectively zero
#: tolerance. Not an Event Notes parameter: it is how the regulations
#: treat a non-race session, independent of the event's escalation config.
_LAP_TIME_DELETED_SESSIONS = frozenset({SessionType.PRACTICE, SessionType.QUALIFYING})


@dataclass(frozen=True)
class ConsequenceResult:
    car_number: int
    strikes: int
    lap_time_deleted: bool
    black_and_white_flag: bool
    penalty_seconds: int


class EscalationEngine:
    """Per-event-weekend strike state, keyed by car number.

    Strikes increment only through confirm_violation, which must only be
    called after a human steward has reviewed and confirmed a Finding.
    There is no automatic path from Finding.violation == True to a strike.
    """

    def __init__(self, config: EventConfig, override_log: OverrideLog | None = None):
        self.config = config
        self.override_log = override_log
        self._strikes: dict[int, int] = {}

    def strikes_for(self, car_number: int) -> int:
        return self._strikes.get(car_number, 0)

    def confirm_violation(
        self,
        finding: Finding,
        session_type: SessionType,
        steward_id: str,
        rationale: str = "",
    ) -> ConsequenceResult:
        """Record a steward's confirmation that `finding` is a violation.

        Increments this car's strike count and computes the session's
        consequence. Every call is written to the override log, whether
        or not one was supplied at construction (a missing log is a
        configuration bug, not a reason to skip the record) — if none was
        given, this raises rather than lose the record silently.
        """
        if self.override_log is None:
            raise RuntimeError(
                "EscalationEngine has no OverrideLog configured; every steward "
                "confirmation must be recorded (Apex Assist plan, Section 0)"
            )

        self._strikes[finding.car_number] = self._strikes.get(finding.car_number, 0) + 1
        strikes = self._strikes[finding.car_number]

        result = self._consequence(finding.car_number, strikes, session_type)

        self.override_log.record(
            steward_id=steward_id,
            event_id=finding.event_id,
            car_number=finding.car_number,
            lap=finding.lap,
            corner=finding.corner,
            system_verdict="violation" if finding.violation else "no_violation",
            human_decision="violation",
            rationale=rationale,
            strikes_after=strikes,
        )
        return result

    def reject_finding(
        self,
        finding: Finding,
        steward_id: str,
        rationale: str = "",
    ) -> None:
        """Record a steward overturning a system-flagged violation.

        No strike is added. This call still must be logged: overturning a
        Finding is exactly the kind of override the log exists to capture.
        """
        if self.override_log is None:
            raise RuntimeError(
                "EscalationEngine has no OverrideLog configured; every steward "
                "decision must be recorded (Apex Assist plan, Section 0)"
            )
        self.override_log.record(
            steward_id=steward_id,
            event_id=finding.event_id,
            car_number=finding.car_number,
            lap=finding.lap,
            corner=finding.corner,
            system_verdict="violation" if finding.violation else "no_violation",
            human_decision="no_violation",
            rationale=rationale,
            strikes_after=None,
        )

    def _consequence(self, car_number: int, strikes: int, session_type: SessionType) -> ConsequenceResult:
        if session_type in _LAP_TIME_DELETED_SESSIONS:
            return ConsequenceResult(
                car_number=car_number,
                strikes=strikes,
                lap_time_deleted=True,
                black_and_white_flag=False,
                penalty_seconds=0,
            )

        esc = self.config.escalation
        black_and_white_flag = strikes == esc.black_and_white_flag_at
        penalty_seconds = 0
        if strikes == esc.second_penalty_at:
            penalty_seconds = esc.second_penalty_seconds
        elif strikes == esc.first_penalty_at:
            penalty_seconds = esc.first_penalty_seconds
        elif strikes > esc.second_penalty_at:
            # Event Notes only define the first two escalation steps
            # explicitly; further strikes repeat the most severe defined
            # penalty rather than silently doing nothing.
            penalty_seconds = esc.second_penalty_seconds

        return ConsequenceResult(
            car_number=car_number,
            strikes=strikes,
            lap_time_deleted=False,
            black_and_white_flag=black_and_white_flag,
            penalty_seconds=penalty_seconds,
        )
