"""Frenet frame for a closed-loop centreline (Apex Assist plan, Section 5.1).

Everything else reduces to this: to_frenet(x, y) -> (s, d) and
to_cartesian(s, d) -> (x, y), built from cumulative arc length plus
nearest-segment projection. The centreline is a closed loop (the last
point implicitly connects back to the first), so s wraps at the
start/finish line rather than needing special-cased handling.
"""
from __future__ import annotations

import numpy as np


class TrackFrame:
    """s: arc length along the centreline, wrapping at total_length.

    d: signed lateral offset from the centreline; positive is to the left
    of the direction of travel (points[i] -> points[i + 1]).
    """

    def __init__(self, centreline_xy):
        points = np.asarray(centreline_xy, dtype=float)
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3:
            raise ValueError("centreline_xy must be an (N, 2) array with N >= 3")

        next_points = np.roll(points, -1, axis=0)
        seg_vecs = next_points - points
        seg_lens = np.linalg.norm(seg_vecs, axis=1)
        if np.any(seg_lens == 0):
            raise ValueError("centreline_xy has duplicate consecutive points")

        self.points = points
        self.seg_vecs = seg_vecs
        self.seg_lens = seg_lens
        self.seg_dirs = seg_vecs / seg_lens[:, None]
        # Left-hand normal of each segment's direction of travel.
        self.seg_normals = np.stack([-self.seg_dirs[:, 1], self.seg_dirs[:, 0]], axis=1)
        self.cum_s = np.concatenate([[0.0], np.cumsum(seg_lens)[:-1]])
        self.total_length = float(seg_lens.sum())

    def to_cartesian(self, s: float, d: float = 0.0) -> tuple[float, float]:
        s_mod = s % self.total_length
        i = int(np.searchsorted(self.cum_s, s_mod, side="right") - 1)
        i = min(max(i, 0), len(self.points) - 1)
        t = (s_mod - self.cum_s[i]) / self.seg_lens[i]
        base = self.points[i] + t * self.seg_vecs[i]
        offset = base + d * self.seg_normals[i]
        return float(offset[0]), float(offset[1])

    def to_frenet(self, x: float, y: float) -> tuple[float, float]:
        point = np.array([x, y], dtype=float)
        w = point - self.points
        t_unclamped = np.einsum("ij,ij->i", w, self.seg_vecs) / (self.seg_lens**2)
        t_clamped = np.clip(t_unclamped, 0.0, 1.0)
        closest = self.points + t_clamped[:, None] * self.seg_vecs
        dists = np.linalg.norm(point - closest, axis=1)
        i = int(np.argmin(dists))

        local = point - self.points[i]
        s_local = float(np.dot(local, self.seg_dirs[i]))
        s_local = min(max(s_local, 0.0), self.seg_lens[i])
        s = self.cum_s[i] + s_local
        d = float(np.dot(local, self.seg_normals[i]))
        return float(s), d
