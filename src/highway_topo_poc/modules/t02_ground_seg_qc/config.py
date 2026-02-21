from __future__ import annotations

from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class Config:
    # Data loading / performance
    processing_max_points: int = 800_000

    # Ground reference
    grid_size_m: float = 1.0
    dem_quantile_q: float = 0.10
    min_points_per_cell: int = 8
    neighbor_cell_radius: int = 2
    neighbor_min_points: int = 32

    # Ground classify
    min_las_ground_points: int = 1000
    above_margin_m: float = 0.08
    below_margin_m: float = 0.20
    max_points_per_cell_export: int = 200
    max_export_points: int = 300_000

    # Traj-clearance QC
    baseline_mode: str = "median"
    threshold_m: float = 0.25
    coverage_gate: float = 0.70
    outlier_gate: float = 0.20
    p99_gate_m: float = 0.40

    # Traj-clearance intervals
    bin_count: int = 64
    bin_outlier_gate: float = 0.30
    min_interval_bins: int = 1
    top_k: int = 5

    # Ground sanity gates
    ground_ratio_min: float = 0.05
    ground_ratio_max: float = 0.95
    ground_count_gate_min: int = 5000

    # Cross-section QC
    xsec_radius_m: float = 12.0
    along_window_m: float = 1.0
    cross_half_width_m: float = 6.0
    xsec_bin_count: int = 21
    xsec_coverage_gate_per_sample: float = 0.35
    xsec_residual_gate_per_sample: float = 0.12

    # Cross-section aggregate gates
    xsec_valid_ratio_gate: float = 0.70
    xsec_p99_abs_res_gate_m: float = 0.15
    xsec_anomaly_ratio_gate: float = 0.20

    # Cross-section intervals
    xsec_interval_bin_count: int = 64
    xsec_bin_anomaly_gate: float = 0.30
    xsec_top_k: int = 5
    xsec_min_interval_bins: int = 1

    # Auto tune
    auto_tune_default: bool = True
    auto_tune_max_trials: int = 24

    # Report size guard
    summary_max_lines: int = 120
    summary_max_bytes: int = 8 * 1024

    def validate(self) -> None:
        if self.processing_max_points < 10_000:
            raise ValueError("processing_max_points must be >= 10000")

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

        if self.min_las_ground_points < 1:
            raise ValueError("min_las_ground_points must be >= 1")
        if self.above_margin_m <= 0:
            raise ValueError("above_margin_m must be > 0")
        if self.below_margin_m <= 0:
            raise ValueError("below_margin_m must be > 0")
        if self.max_points_per_cell_export < 1:
            raise ValueError("max_points_per_cell_export must be >= 1")
        if self.max_export_points < 100:
            raise ValueError("max_export_points must be >= 100")

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

        if not 0.0 <= self.ground_ratio_min <= 1.0:
            raise ValueError("ground_ratio_min must be within [0,1]")
        if not 0.0 <= self.ground_ratio_max <= 1.0:
            raise ValueError("ground_ratio_max must be within [0,1]")
        if self.ground_ratio_min > self.ground_ratio_max:
            raise ValueError("ground_ratio_min must be <= ground_ratio_max")
        if self.ground_count_gate_min < 1:
            raise ValueError("ground_count_gate_min must be >= 1")

        if self.xsec_radius_m <= 0:
            raise ValueError("xsec_radius_m must be > 0")
        if self.along_window_m <= 0:
            raise ValueError("along_window_m must be > 0")
        if self.cross_half_width_m <= 0:
            raise ValueError("cross_half_width_m must be > 0")
        if self.xsec_bin_count < 3:
            raise ValueError("xsec_bin_count must be >= 3")
        if not 0.0 <= self.xsec_coverage_gate_per_sample <= 1.0:
            raise ValueError("xsec_coverage_gate_per_sample must be within [0,1]")
        if self.xsec_residual_gate_per_sample <= 0:
            raise ValueError("xsec_residual_gate_per_sample must be > 0")

        if not 0.0 <= self.xsec_valid_ratio_gate <= 1.0:
            raise ValueError("xsec_valid_ratio_gate must be within [0,1]")
        if self.xsec_p99_abs_res_gate_m <= 0:
            raise ValueError("xsec_p99_abs_res_gate_m must be > 0")
        if not 0.0 <= self.xsec_anomaly_ratio_gate <= 1.0:
            raise ValueError("xsec_anomaly_ratio_gate must be within [0,1]")

        if self.xsec_interval_bin_count < 1:
            raise ValueError("xsec_interval_bin_count must be >= 1")
        if not 0.0 <= self.xsec_bin_anomaly_gate <= 1.0:
            raise ValueError("xsec_bin_anomaly_gate must be within [0,1]")
        if self.xsec_top_k < 1:
            raise ValueError("xsec_top_k must be >= 1")
        if self.xsec_min_interval_bins < 1:
            raise ValueError("xsec_min_interval_bins must be >= 1")

        if self.auto_tune_max_trials < 1:
            raise ValueError("auto_tune_max_trials must be >= 1")

        if self.summary_max_lines < 1:
            raise ValueError("summary_max_lines must be >= 1")
        if self.summary_max_bytes < 256:
            raise ValueError("summary_max_bytes must be >= 256")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def with_updates(self, **kwargs: object) -> "Config":
        return replace(self, **kwargs)
