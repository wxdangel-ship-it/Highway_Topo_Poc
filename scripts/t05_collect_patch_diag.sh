#!/usr/bin/env bash
set -euo pipefail

RUN_ID=""
PATCH_IDS=""
OUT_ROOT="outputs/_work/t05_topology_between_rc"

while [ $# -gt 0 ]; do
  case "$1" in
    --run_id) RUN_ID="$2"; shift 2 ;;
    --patch_ids) PATCH_IDS="$2"; shift 2 ;;
    --out_root) OUT_ROOT="$2"; shift 2 ;;
    *)
      echo "ERROR: unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if [ -z "$RUN_ID" ] || [ -z "$PATCH_IDS" ]; then
  echo "ERROR: --run_id and --patch_ids are required" >&2
  exit 2
fi

IFS=',' read -r -a PATCH_ARR <<< "$PATCH_IDS"

for PID_RAW in "${PATCH_ARR[@]}"; do
  PID="$(echo "$PID_RAW" | xargs)"
  [ -z "$PID" ] && continue
  PATCH_DIR="$OUT_ROOT/$RUN_ID/patches/$PID"

  python3 - "$PATCH_DIR" "$PID" <<'PY'
import json
import sys
from pathlib import Path

patch_dir = Path(sys.argv[1])
pid = str(sys.argv[2])

print(f"\n===== PATCH {pid} =====")
print(f"patch_dir={patch_dir}")

def load_json(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_parse_error": str(exc)}

road_fc = load_json(patch_dir / "Road.geojson")
road_props = {}
if isinstance(road_fc, dict):
    feats = road_fc.get("features") or []
    if feats:
        road_props = feats[0].get("properties") or {}

road_keys = [
    "road_id",
    "endpoint_anchor_dist_dst_m",
    "endpoint_dist_to_xsec_dst_m",
    "xsec_target_mode_dst",
    "xsec_road_selected_by_dst",
    "xsec_gate_fallback_dst",
    "xsec_gate_selected_by_dst",
    "xsec_gate_len_dst_m",
    "drivezone_fallback_used",
    "step1_strategy",
    "step1_corridor_count",
    "step1_main_corridor_ratio",
    "hard_reasons",
    "soft_issue_flags",
]
for k in road_keys:
    print(f"{k}={road_props.get(k)}")

metrics = load_json(patch_dir / "metrics.json")
if not isinstance(metrics, dict):
    metrics = {}
metric_keys = [
    "xsec_gate_fallback_src_count",
    "xsec_gate_fallback_dst_count",
    "traj_drop_count_by_drivezone",
    "drivezone_fallback_used_count",
    "step1_corridor_count_p90",
    "step1_main_corridor_ratio_p50",
]
for k in metric_keys:
    print(f"{k}={metrics.get(k)}")

debug_files = [
    "debug/xsec_gate_selected_dst.geojson",
    "debug/step2_xsec_road_selected_dst.geojson",
    "debug/step3_endpoint_src_dst.geojson",
]
for rel in debug_files:
    fc = load_json(patch_dir / rel)
    if not isinstance(fc, dict):
        print(f"{rel}: exists=False")
        continue
    feats = fc.get("features") or []
    print(f"{rel}: exists=True feature_count={len(feats)}")
    if feats:
        p = feats[0].get("properties") or {}
        keep_keys = [
            "road_id",
            "endpoint_tag",
            "dist_to_xsec",
            "selected_by",
            "shift_used",
            "mid_to_ref_m",
            "fallback_flag",
            "gate_len_m",
        ]
        sample = {k: p.get(k) for k in keep_keys if k in p}
        print(f"{rel}: sample_props={json.dumps(sample, ensure_ascii=False)}")
    if rel.endswith("step3_endpoint_src_dst.geojson"):
        dst_dist = []
        for f in feats:
            pp = f.get("properties") or {}
            if pp.get("endpoint_tag") == "dst":
                dst_dist.append(pp.get("dist_to_xsec"))
        print(f"{rel}: dst_dist_to_xsec_list={json.dumps(dst_dist, ensure_ascii=False)}")
PY
done
