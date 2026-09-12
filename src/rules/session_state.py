"""Per-session record of incidents already penalised on other grounds.

Section 5.6's exception_part_of_penalised_incident takes a session_state
argument rather than a bare bool so rules/ stays decoupled from how the
incident/penalty record is actually stored (console DB, in-memory during a
sprint, whatever) — this is the seam, kept deliberately minimal.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SessionState:
    penalized_event_ids: frozenset[str] = field(default_factory=frozenset)

    def is_penalized(self, event_id: str) -> bool:
        return event_id in self.penalized_event_ids
