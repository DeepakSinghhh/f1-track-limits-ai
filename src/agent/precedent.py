"""Within-session precedent store (Section 5.8): "the highest-value part
of the agent tier -- consistency within a session is what stewards are
most criticised for."

A feature vector per resolved event plus nearest-neighbour retrieval by
plain Euclidean distance -- no training, no vector database. A session
has at most a few hundred resolved events; this is a handful of floats
each, not an embeddings problem.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from src.schemas import EventType, ExcursionEvent, Verdict

_EVENT_TYPE_ORDER = list(EventType)


def _feature_vector(corner: int, duration_s: float, max_margin_m: float, wheels_off_peak: int | None, event_type: EventType) -> tuple[float, ...]:
    return (
        float(corner),
        duration_s,
        max_margin_m,
        float(wheels_off_peak) if wheels_off_peak is not None else -1.0,
        float(_EVENT_TYPE_ORDER.index(event_type)),
    )


@dataclass(frozen=True)
class Precedent:
    event_id: str
    corner: int
    event_type: EventType
    verdict: Verdict
    features: tuple[float, ...]


@dataclass
class PrecedentStore:
    _precedents: list[Precedent] = field(default_factory=list)

    def record(self, event: ExcursionEvent, verdict: Verdict) -> None:
        self._precedents.append(
            Precedent(
                event_id=event.event_id,
                corner=event.corner,
                event_type=event.proposed_type,
                verdict=verdict,
                features=_feature_vector(
                    event.corner, event.duration_s, event.max_margin_m, event.wheels_off_peak, event.proposed_type
                ),
            )
        )

    def __len__(self) -> int:
        return len(self._precedents)

    def find_similar(self, corner: int, event_type: EventType, k: int = 5) -> list[Precedent]:
        """Exact corner + event-type match first (that's the actual
        question a steward asks -- "how was this corner called today"),
        falling back to nearest by feature distance so the agent still
        has something comparable to cite when nothing exact exists yet.
        """
        exact = [p for p in self._precedents if p.corner == corner and p.event_type == event_type]
        if exact:
            return exact[-k:]

        if not self._precedents:
            return []

        query = _feature_vector(corner, 0.0, 0.0, None, event_type)
        by_distance = sorted(self._precedents, key=lambda p: math.dist(p.features, query))
        return by_distance[:k]
