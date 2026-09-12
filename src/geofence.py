"""Demo-pipeline candidate-event tracker (app.py / detector.py).

Turns a per-frame zone-crossing boolean into ExcursionEvents via
hysteresis + a duration gate — the same shape as src.events.localise, but
driven by a single boolean per frame rather than a full CarState stream,
since this pipeline has no Frenet frame or per-wheel data.

This module never decides a violation and never touches a strike count.
See src.rules.engine.RuleEngine for the (deterministic) verdict and
src.rules.escalation.EscalationEngine for strikes, which move only on
explicit steward confirmation — this tracker's job ends at producing a
candidate event for the rule engine to evaluate.
"""
from __future__ import annotations

import uuid

from src.schemas import EventType, ExcursionEvent, RelationalContext


class ZoneCrossingTracker:
    """violating: bool per frame -> ExcursionEvent once a crossing closes.

    Two honesty notes, not placeholders to "fill in later":

    - wheels_off_peak is always None here. This pipeline detects a single
      reference point per vehicle (the bounding box's bottom-centre), not
      per-wheel contact patches — Section 5.3 is explicit that a centroid
      (or any single point) is "indefensible under questioning" as an
      Art. 33.3 measurement. The rule engine already handles a None
      wheels_off_peak correctly: it reports INSUFFICIENT_EVIDENCE rather
      than guessing, which is the honest outcome for what this detector
      can actually measure.
    - max_margin_m is always 0.0: the zone is a fixed screen-space region
      (not a calibrated track boundary via src.track.boundary), so there
      is no real metric distance to report. 0.0 is not "zero margin", it
      is "not measured" — callers must not treat it as a real quantity.

    There is also no cross-frame vehicle identity (ByteTrack, Section
    5.3) here: one tracker instance follows "is anything in view over the
    zone", not a specific car by ID. car_number is a caller-supplied
    placeholder for exactly that reason.
    """

    def __init__(self, fps: float, min_duration_s: float, car_number: int = 0):
        self.fps = fps
        self.min_duration_s = min_duration_s
        self.car_number = car_number
        self._in_excursion = False
        self._onset_frame: int | None = None

    def update(self, is_violating: bool, frame_id: int) -> ExcursionEvent | None:
        """Call once per frame. Returns a completed ExcursionEvent only on
        the frame the crossing closes (violating -> not violating).
        """
        if is_violating:
            if not self._in_excursion:
                self._in_excursion = True
                self._onset_frame = frame_id
            return None

        if self._in_excursion:
            onset_frame = self._onset_frame
            self._in_excursion = False
            self._onset_frame = None
            return self._build_event(onset_frame, frame_id)
        return None

    def close(self, frame_id: int) -> ExcursionEvent | None:
        """Close a still-open excursion when the stream ends (e.g. the
        clip runs out) rather than silently dropping it.
        """
        if not self._in_excursion:
            return None
        onset_frame = self._onset_frame
        self._in_excursion = False
        self._onset_frame = None
        return self._build_event(onset_frame, frame_id)

    def _build_event(self, onset_frame: int, reentry_frame: int) -> ExcursionEvent:
        t_onset = onset_frame / self.fps
        t_reentry = reentry_frame / self.fps
        duration_s = max(t_reentry - t_onset, 0.0)
        proposed_type = (
            EventType.MEASUREMENT_ARTEFACT
            if duration_s < self.min_duration_s
            else EventType.EXCURSION_NO_ADVANTAGE
        )
        return ExcursionEvent(
            event_id=str(uuid.uuid4()),
            car_number=self.car_number,
            lap=0,  # no lap counter in this pipeline
            corner=0,  # no corner map — matches config/events/demo_clip.yaml's single corner
            t_onset=t_onset,
            t_max_excursion=t_onset,  # a boolean signal has no distinguishable peak
            t_reentry=t_reentry,
            max_margin_m=0.0,  # not measured — see class docstring
            margin_sigma_m=0.0,  # not measured — see class docstring
            duration_s=duration_s,
            wheels_off_peak=None,  # not measured — see class docstring
            proposed_type=proposed_type,
            relational=RelationalContext(
                car_number=self.car_number,
                session_time=t_onset,
                alongside=[],
                nearest_delta_s=float("inf"),
                nearest_delta_d=float("inf"),
                yellow_flag_sector=False,
            ),
        )
