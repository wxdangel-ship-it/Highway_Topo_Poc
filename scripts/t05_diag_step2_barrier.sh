#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/t05_step_common.sh"

REPO_ROOT="$(t05_repo_root)"
OUT_ROOT="$(t05_default_out_root "$REPO_ROOT")"
RUN_ID=""
PATCH_ID=""
ROAD_ID=""

while [ $# -gt 0 ]; do
  case "$1" in
    --run_id) RUN_ID="$2"; shift 2 ;;
    --patch_id) PATCH_ID="$2"; shift 2 ;;
    --road_id) ROAD_ID="$2"; shift 2 ;;
    --out_root) OUT_ROOT="$2"; shift 2 ;;
    *)
      echo "ERROR: unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if [ -z "$RUN_ID" ] || [ -z "$PATCH_ID" ]; then
  echo "ERROR: --run_id and --patch_id are required" >&2
  exit 2
fi

PY="$(t05_python_bin "$REPO_ROOT")"
PATCH_OUT="$(t05_patch_out_dir "$OUT_ROOT" "$RUN_ID" "$PATCH_ID")"
METRICS_JSON="$PATCH_OUT/metrics.json"
ROAD_JSON="$PATCH_OUT/road.geojson"
SRC_SAMPLES="$PATCH_OUT/debug/step2_xsec_barrier_samples_src.geojson"
DST_SAMPLES="$PATCH_OUT/debug/step2_xsec_barrier_samples_dst.geojson"

if [ ! -f "$METRICS_JSON" ] || [ ! -f "$ROAD_JSON" ]; then
  echo "ERROR: missing metrics.json or road.geojson under $PATCH_OUT" >&2
  exit 1
fi

"$PY" - "$METRICS_JSON" "$ROAD_JSON" "$SRC_SAMPLES" "$DST_SAMPLES" "$ROAD_ID" "$PATCH_OUT" <<'PY'
import json
import sys
import numpy as np

metrics_path = sys.argv[1]
road_path = sys.argv[2]
src_path = sys.argv[3]
dst_path = sys.argv[4]
road_id_arg = str(sys.argv[5] or "")
patch_out = sys.argv[6]

def load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
            if isinstance(obj, dict):
                return obj
    except Exception:
        pass
    return {}

def sample_stats(fc: dict) -> dict:
    feats = fc.get("features") or []
    ng = np.asarray([float((f.get("properties") or {}).get("ng_count") or 0.0) for f in feats], dtype=np.float64)
    occ = np.asarray([float((f.get("properties") or {}).get("occupancy_ratio") or 0.0) for f in feats], dtype=np.float64)
    cand = int(sum(bool((f.get("properties") or {}).get("barrier_candidate")) for f in feats))
    fin = int(sum(bool((f.get("properties") or {}).get("barrier_final")) for f in feats))
    out = {
        "samples": int(len(feats)),
        "candidate_samples": cand,
        "final_samples": fin,
        "ng_max": None,
        "ng_p90": None,
        "ng_p50": None,
        "occ_max": None,
        "occ_p90": None,
        "occ_p50": None,
    }
    if ng.size > 0:
        out["ng_max"] = float(np.max(ng))
        out["ng_p90"] = float(np.percentile(ng, 90))
        out["ng_p50"] = float(np.percentile(ng, 50))
    if occ.size > 0:
        out["occ_max"] = float(np.max(occ))
        out["occ_p90"] = float(np.percentile(occ, 90))
        out["occ_p50"] = float(np.percentile(occ, 50))
    return out

metrics = load_json(metrics_path)
road_fc = load_json(road_path)
feats = road_fc.get("features") or []
picked = None
if road_id_arg:
    for f in feats:
        p = f.get("properties") or {}
        if str(p.get("road_id") or "") == road_id_arg:
            picked = f
            break
if picked is None and feats:
    picked = feats[0]

p = (picked or {}).get("properties") or {}
road_id = str(p.get("road_id") or road_id_arg or "")

src_stats = sample_stats(load_json(src_path))
dst_stats = sample_stats(load_json(dst_path))

print("=== Step2 Barrier Diagnose ===")
print("patch_out =", patch_out)
print("road_id =", road_id)
print("")
print("pointcloud_bbox_point_count =", metrics.get("pointcloud_bbox_point_count"))
print("pointcloud_selected_point_count =", metrics.get("pointcloud_selected_point_count"))
print("pointcloud_non_ground_selected_point_count =", metrics.get("pointcloud_non_ground_selected_point_count"))
print("pointcloud_cache_hit =", metrics.get("pointcloud_cache_hit"))
print("")
keys = [
    "xsec_selected_by_src",
    "xsec_selected_by_dst",
    "xsec_shift_used_m_src",
    "xsec_shift_used_m_dst",
    "xsec_barrier_candidate_count_src",
    "xsec_barrier_candidate_count_dst",
    "xsec_barrier_final_count_src",
    "xsec_barrier_final_count_dst",
]
for k in keys:
    print(f"{k} =", p.get(k))
print("")
print("src_samples =", src_stats)
print("dst_samples =", dst_stats)
PY

