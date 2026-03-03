from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


DEFAULT_PARAMS: dict[str, Any] = {
    "cross_half_len_m": 30.0,
    "scan_step_m": 1.0,
    "scan_near_limit_m": 20.0,
    "scan_max_limit_m": 200.0,
    "stop_at_next_intersection": True,
    "divstrip_hit_tol_m": 1.0,
    "divstrip_trigger_window_m": 3.0,
    "pc_use_classification": True,
    "pc_ground_class": 2,
    "pc_ignore_classes": [12],
    "pc_non_ground_class": 1,
    "pc_non_ground_min_points": 5,
    "pc_line_buffer_m": 0.5,
    "ignore_end_margin_m": 3.0,
    "ignore_initial_side_ng": True,
    "traj_buffer_m": 1.5,
    "suppress_ng_near_traj": True,
    "use_drivezone": True,
    "drivezone_merge_mode": "unary_union",
    "min_piece_len_m": 1.0,
    "divstrip_anchor_snap_enabled": False,
    "divstrip_preferred_window_m": 8.0,
    "divstrip_ref_hard_window_m": 1.0,
    "divstrip_drivezone_max_offset_m": 30.0,
    "reverse_tip_max_m": 10.0,
    "output_cross_half_len_m": 120.0,
    "current_road_edge_pad_m": 4.0,
    "continuous_enable": True,
    "continuous_dist_max_m": 50.0,
    "continuous_merge_max_gap_m": 5.0,
    "continuous_merge_geom_tol_m": 1.0,
    "next_intersection_degree_min": 3,
    "stop_intersection_require_connected": True,
    "disable_geometric_stop_fallback": True,
    "min_anchor_found_ratio_focus": 1.0,
    "min_anchor_found_ratio_patch": 0.90,
    "no_trigger_count_max_focus": 0,
    "scan_exceed_200m_count_max_focus": 0,
    "no_trigger_count_max_patch": 999999,
    "scan_exceed_200m_count_max_patch": 999999,
}


DEFAULT_RUNTIME: dict[str, Any] = {
    "mode": "global_focus",
    "out_root": "outputs/_work/t04_rc_sw_anchor",
    "run_id": "auto",
    "src_crs": "auto",
    "dst_crs": "EPSG:3857",
    "node_src_crs": "auto",
    "road_src_crs": "auto",
    "divstrip_src_crs": "auto",
    "traj_src_crs": "auto",
    "pointcloud_crs": "auto",
    "patch_dir": None,
    "global_node_path": None,
    "global_road_path": None,
    "divstrip_path": None,
    "drivezone_path": None,
    "pointcloud_path": None,
    "traj_glob": None,
    "focus_node_ids": [],
    "drivezone_src_crs": "auto",
}


def _coerce_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid_bool: {raw}")


def _coerce_like(template_value: Any, raw_value: Any) -> Any:
    if isinstance(template_value, bool):
        return _coerce_bool(raw_value)
    if isinstance(template_value, int) and not isinstance(template_value, bool):
        return int(raw_value)
    if isinstance(template_value, float):
        return float(raw_value)
    if isinstance(template_value, list):
        if isinstance(raw_value, list):
            return list(raw_value)
        return [raw_value]
    if template_value is None:
        return raw_value
    return str(raw_value)


def parse_set_overrides(items: list[str] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"invalid_set_item: {item}")
        key, raw = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"invalid_set_item: {item}")
        out[key] = raw.strip()
    return out


def _parse_focus_ids_text(raw: str) -> list[str]:
    parts = [x.strip() for x in raw.split(",")]
    return [p for p in parts if p]


def _dedup_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        key = str(item).strip()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def load_focus_node_ids_file(path: Path) -> list[str]:
    if not path.is_file():
        raise ValueError(f"focus_node_ids_file_not_found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".txt":
        lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
        return _dedup_keep_order([x for x in lines if x])

    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            vals = payload.get("focus_node_ids")
            if not isinstance(vals, list):
                raise ValueError("focus_node_ids_file_json_missing_focus_node_ids")
            return _dedup_keep_order([str(x) for x in vals])
        if isinstance(payload, list):
            return _dedup_keep_order([str(x) for x in payload])
        raise ValueError("focus_node_ids_file_json_invalid")

    if suffix == ".csv":
        rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
        if not rows:
            return []
        header = [c.strip().lower() for c in rows[0]]
        start_idx = 1 if any(header) else 0
        node_col = 0
        if "nodeid" in header:
            node_col = header.index("nodeid")
        values: list[str] = []
        for row in rows[start_idx:]:
            if node_col >= len(row):
                continue
            v = row[node_col].strip()
            if v:
                values.append(v)
        return _dedup_keep_order(values)

    raise ValueError(f"unsupported_focus_node_ids_file_suffix: {path}")


def _normalize_paths(runtime: dict[str, Any]) -> None:
    path_keys = [
        "patch_dir",
        "out_root",
        "global_node_path",
        "global_road_path",
        "divstrip_path",
        "drivezone_path",
        "pointcloud_path",
        "traj_glob",
        "config_json",
    ]
    for key in path_keys:
        val = runtime.get(key)
        if val is None:
            continue
        if isinstance(val, Path):
            runtime[key] = str(val)
            continue
        runtime[key] = str(val)


def resolve_runtime_config(
    *,
    config_json: Path | None,
    cli_overrides: dict[str, Any],
    set_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg_payload: dict[str, Any] = {}
    if config_json is not None:
        payload = json.loads(config_json.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("config_json_must_be_object")
        cfg_payload = dict(payload)

    runtime = dict(DEFAULT_RUNTIME)
    runtime.update({k: v for k, v in cfg_payload.items() if k != "params"})
    runtime.update(
        {
            k: v
            for k, v in cli_overrides.items()
            if v is not None and k not in {"focus_node_ids", "focus_node_ids_file"} and k not in DEFAULT_PARAMS
        }
    )

    params = dict(DEFAULT_PARAMS)
    raw_params = cfg_payload.get("params", {})
    if raw_params:
        if not isinstance(raw_params, dict):
            raise ValueError("params_must_be_object")
        for key, value in raw_params.items():
            if key not in params:
                raise ValueError(f"unknown_param_key: {key}")
            params[key] = _coerce_like(DEFAULT_PARAMS[key], value)

    for key, value in (set_overrides or {}).items():
        if key not in params:
            raise ValueError(f"unknown_param_key: {key}")
        params[key] = _coerce_like(DEFAULT_PARAMS[key], value)

    for key, value in cli_overrides.items():
        if value is None:
            continue
        if key not in params:
            continue
        params[key] = _coerce_like(DEFAULT_PARAMS[key], value)

    # Focus NodeIDs precedence: CLI string/file > config_json field
    focus_ids: list[str] = []
    if isinstance(runtime.get("focus_node_ids"), list):
        focus_ids = [str(x) for x in runtime.get("focus_node_ids", [])]

    cli_ids_raw = cli_overrides.get("focus_node_ids")
    cli_ids_file = cli_overrides.get("focus_node_ids_file")
    if cli_ids_raw is not None:
        focus_ids = _parse_focus_ids_text(str(cli_ids_raw))
    elif cli_ids_file is not None:
        focus_ids = load_focus_node_ids_file(Path(str(cli_ids_file)))

    runtime["focus_node_ids"] = _dedup_keep_order(focus_ids)
    runtime["params"] = params
    runtime["config_json"] = str(config_json) if config_json else None

    _normalize_paths(runtime)

    mode = str(runtime.get("mode", "global_focus")).strip().lower()
    if mode not in {"global_focus", "patch"}:
        raise ValueError(f"invalid_mode: {mode}")
    runtime["mode"] = mode

    if not runtime.get("patch_dir"):
        raise ValueError("patch_dir_required")

    if mode == "global_focus":
        if not runtime.get("global_node_path"):
            raise ValueError("global_node_path_required_for_global_focus")
        if not runtime.get("global_road_path"):
            raise ValueError("global_road_path_required_for_global_focus")
        if not runtime.get("focus_node_ids"):
            raise ValueError("focus_node_ids_required_for_global_focus")

    return runtime


__all__ = [
    "DEFAULT_PARAMS",
    "DEFAULT_RUNTIME",
    "load_focus_node_ids_file",
    "parse_set_overrides",
    "resolve_runtime_config",
]
