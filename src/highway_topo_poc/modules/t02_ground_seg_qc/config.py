from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Config:
    # Ground reference
    grid_size_m: float = 1.0
    dem_quantile_q: float = 0.10
    min_points_per_cell: int = 8
    neighbor_cell_radius: int = 2
    neighbor_min_points: int = 32

    # QC
    baseline_mode: str = "median"
    threshold_m: float = 0.25
    coverage_gate: float = 0.70
    outlier_gate: float = 0.20
    p99_gate_m: float = 0.40

    # Intervals
    bin_count: int = 64
    bin_outlier_gate: float = 0.30
    min_interval_bins: int = 1
    top_k: int = 5

    # Report size guard
    summary_max_lines: int = 120
    summary_max_bytes: int = 8 * 1024

    def validate(self) -> None:
        if self.grid_size_m <= 0:
            raise ValueError("grid_size_m must be > 0")
        if not 0.0 <= self.dem_quantile_q <= 1.0:
            raise ValueError("dem_quantile_q must be within [0,1]")
        if self.min_points_per_cell < 1:
            raise ValueError("min_points_per_cell must be >= 1")
        if self.neighbor_cell_radius < 0:
            raise ValueError("neighbor_cell_radius must be >= 0")
        if self.neighbor_min_points < 1:
            raise ValueError("neighbor_min_points must be >= 1")
        if self.baseline_mode not in {"median", "mean"}:
            raise ValueError("baseline_mode must be one of: median, mean")
        if self.threshold_m <= 0:
            raise ValueError("threshold_m must be > 0")
        if not 0.0 <= self.coverage_gate <= 1.0:
            raise ValueError("coverage_gate must be within [0,1]")
        if not 0.0 <= self.outlier_gate <= 1.0:
            raise ValueError("outlier_gate must be within [0,1]")
        if self.p99_gate_m <= 0:
            raise ValueError("p99_gate_m must be > 0")
        if self.bin_count < 1:
            raise ValueError("bin_count must be >= 1")
        if not 0.0 <= self.bin_outlier_gate <= 1.0:
            raise ValueError("bin_outlier_gate must be within [0,1]")
        if self.min_interval_bins < 1:
            raise ValueError("min_interval_bins must be >= 1")
        if self.top_k < 1:
            raise ValueError("top_k must be >= 1")
        if self.summary_max_lines < 1:
            raise ValueError("summary_max_lines must be >= 1")
        if self.summary_max_bytes < 256:
            raise ValueError("summary_max_bytes must be >= 256")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
