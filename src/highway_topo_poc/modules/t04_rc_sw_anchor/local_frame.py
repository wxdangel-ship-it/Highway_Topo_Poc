from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from shapely.geometry import LineString


def normalize_vec(vx: float, vy: float) -> tuple[float, float]:
    n = math.hypot(float(vx), float(vy))
    if n <= 1e-9:
        return (1.0, 0.0)
    return (float(vx) / n, float(vy) / n)


@dataclass(frozen=True)
class LocalFrame:
    origin_x: float
    origin_y: float
    tangent_u: tuple[float, float]

    @property
    def perp_v(self) -> tuple[float, float]:
        tx, ty = self.tangent_u
        return (-ty, tx)

    @classmethod
    def from_tangent(cls, *, origin_xy: tuple[float, float], tangent_xy: tuple[float, float]) -> "LocalFrame":
        tx, ty = normalize_vec(tangent_xy[0], tangent_xy[1])
        return cls(origin_x=float(origin_xy[0]), origin_y=float(origin_xy[1]), tangent_u=(tx, ty))

    def project_xy(self, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if xy.size == 0:
            return np.zeros((0,), dtype=np.float64), np.zeros((0,), dtype=np.float64)
        tx, ty = self.tangent_u
        px, py = self.perp_v
        dx = np.asarray(xy[:, 0], dtype=np.float64) - self.origin_x
        dy = np.asarray(xy[:, 1], dtype=np.float64) - self.origin_y
        u = dx * tx + dy * ty
        v = dx * px + dy * py
        return u, v

    def crossline(self, *, scan_dist_m: float, cross_half_len_m: float) -> LineString:
        tx, ty = self.tangent_u
        px, py = self.perp_v
        cx = self.origin_x + tx * float(scan_dist_m)
        cy = self.origin_y + ty * float(scan_dist_m)
        hx = float(cross_half_len_m) * px
        hy = float(cross_half_len_m) * py
        return LineString([(cx - hx, cy - hy), (cx + hx, cy + hy)])


__all__ = ["LocalFrame", "normalize_vec"]
