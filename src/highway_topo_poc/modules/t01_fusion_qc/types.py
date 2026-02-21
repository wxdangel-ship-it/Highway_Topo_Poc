from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class PatchCandidate:
    cloud_path: Path
    traj_path: Path
    patch_key: str


@dataclass(frozen=True)
class TrajectoryData:
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    sort_field: str | None


@dataclass(frozen=True)
class CloudMeta:
    used_cloud_path: Path
    point_count: int
    min_x: float
    min_y: float
    max_x: float
    max_y: float


@dataclass(frozen=True)
class BinRecord:
    bin_index: int
    start_idx: int
    end_idx: int
    valid_fraction: float
    valid_count: int
    bin_score: float | None
    insufficient_coverage: bool
    abnormal: bool


@dataclass(frozen=True)
class IntervalRecord:
    start_bin: int
    end_bin: int
    len_bins: int
    interval_score: float
    start_idx: int
    end_idx: int


@dataclass(frozen=True)
class MetricsRecord:
    n_traj: int
    n_valid: int
    coverage: float
    p50: float | None
    p90: float | None
    p99: float | None
    threshold_A: float | None
    status: str
    backend: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PatchAnalysis:
    patch_key: str
    cloud_path: str
    traj_path: str
    metrics: MetricsRecord
    bins: list[BinRecord]
    intervals: list[IntervalRecord]
