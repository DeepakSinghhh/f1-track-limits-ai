"""Track boundary model (Apex Assist plan, Section 5.1).

half_width(s) -> (w_left, w_right) and signed_distance_to_edge(s, d) -> float,
positive meaning outside the track. The decision surface is the OUTER edge
of the white line (F1SR Art. 33.3), not the painted/inner edge, so the
usable half-width is the painted half-width plus the line's own width
(white_line_width_m, from Event Notes config) — not a track/rules
constant, hence a constructor argument rather than hardcoded here.
"""
from __future__ import annotations

import numpy as np


class Boundary:
    def __init__(
        self,
        s_samples,
        painted_half_width_left,
        painted_half_width_right,
        white_line_width_m: float,
        total_length: float,
    ):
        s_samples = np.asarray(s_samples, dtype=float)
        left = np.asarray(painted_half_width_left, dtype=float)
        right = np.asarray(painted_half_width_right, dtype=float)
        if not (len(s_samples) == len(left) == len(right)) or len(s_samples) < 2:
            raise ValueError("s_samples, painted_half_width_left/right must be equal length, >= 2")

        self.s_samples = s_samples
        self.white_line_width_m = white_line_width_m
        self.total_length = total_length
        self.half_width_left = left + white_line_width_m
        self.half_width_right = right + white_line_width_m

    def half_width(self, s: float) -> tuple[float, float]:
        s_mod = s % self.total_length
        w_left = float(np.interp(s_mod, self.s_samples, self.half_width_left, period=self.total_length))
        w_right = float(np.interp(s_mod, self.s_samples, self.half_width_right, period=self.total_length))
        return w_left, w_right

    def signed_distance_to_edge(self, s: float, d: float) -> float:
        """Positive means outside the track (beyond the outer white line edge)."""
        w_left, w_right = self.half_width(s)
        if d >= 0:
            return d - w_left
        return -d - w_right
