#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/t05_step_common.sh"

REPO_ROOT="$(t05_repo_root)"
OUT_ROOT="$(t05_default_out_root "$REPO_ROOT")"
RUN_ID=""
PATCH_ID=""
ROAD_ID=""
SEP_M="8.0"

while [ $# -gt 0 ]; do
  case "$1" in
    --run_id) RUN_ID="$2"; shift 2 ;;
    --patch_id) PATCH_ID="$2"; shift 2 ;;
    --road_id) ROAD_ID="$2"; shift 2 ;;
    --out_root) OUT_ROOT="$2"; shift 2 ;;
    --sep_m) SEP_M="$2"; shift 2 ;;
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
SUPPORT_FC="$PATCH_OUT/debug/step1_support_trajs.geojson"
GATE_JSON="$PATCH_OUT/gate.json"

if [ ! -f "$SUPPORT_FC" ]; then
  echo "ERROR: missing file: $SUPPORT_FC" >&2
  exit 1
fi

if [ -z "$ROAD_ID" ] && [ -f "$GATE_JSON" ]; then
  ROAD_ID="$("$PY" - "$GATE_JSON" <<'PY'
import json
import sys
path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as f:
        gate = json.load(f)
except Exception:
    print("")
    raise SystemExit(0)
for bp in (gate.get("hard_breakpoints") or []):
    if str(bp.get("reason")) == "MULTI_CORRIDOR":
        rid = str(bp.get("road_id") or "")
        if rid:
            print(rid)
            raise SystemExit(0)
print("")
PY
)"
fi

if [ -z "$ROAD_ID" ]; then
  echo "ERROR: road_id is empty. pass --road_id <src_dst> or ensure gate has MULTI_CORRIDOR record" >&2
  exit 1
fi

"$PY" - "$SUPPORT_FC" "$GATE_JSON" "$ROAD_ID" "$SEP_M" "$PATCH_OUT" <<'PY'
import json
import math
import sys
from collections import defaultdict

import numpy as np
from shapely.geometry import shape

support_fc_path = sys.argv[1]
gate_json_path = sys.argv[2]
road_id = str(sys.argv[3])
sep_m = float(sys.argv[4])
patch_out = sys.argv[5]

def cluster_1d(values: np.ndarray, tol: float) -> tuple[list[int], list[float]]:
    if values.size == 0:
        return [], []
    order = np.argsort(values)
    labels = [-1 for _ in range(values.size)]
    centers: list[float] = []
    counts: list[int] = []
    for idx in order:
        v = float(values[int(idx)])
        assigned = False
        for cid, c in enumerate(centers):
            if abs(v - c) <= float(tol):
                labels[int(idx)] = cid
                counts[cid] += 1
                centers[cid] = centers[cid] + (v - centers[cid]) / float(counts[cid])
                assigned = True
                break
        if not assigned:
            labels[int(idx)] = len(centers)
            centers.append(v)
            counts.append(1)
    return labels, centers

def safe_mid_xy(geom):
    try:
        p = geom.interpolate(0.5, normalized=True)
        return (float(p.x), float(p.y))
    except Exception:
        return None

hard_hint = None
try:
    with open(gate_json_path, "r", encoding="utf-8") as f:
        gate = json.load(f)
    for bp in (gate.get("hard_breakpoints") or []):
        if str(bp.get("road_id") or "") == road_id and str(bp.get("reason") or "") == "MULTI_CORRIDOR":
            hard_hint = str(bp.get("hint") or "")
            break
except Exception:
    hard_hint = None

with open(support_fc_path, "r", encoding="utf-8") as f:
    fc = json.load(f)

items: list[dict] = []
road_counts: dict[str, int] = defaultdict(int)
for feat in (fc.get("features") or []):
    prop = feat.get("properties") or {}
    rid = str(prop.get("road_id") or "")
    if rid:
        road_counts[rid] += 1
    if rid != road_id:
        continue
    geom_raw = feat.get("geometry")
    if not isinstance(geom_raw, dict):
        continue
    try:
        geom = shape(geom_raw)
    except Exception:
        continue
    tid = str(prop.get("traj_id") or "")
    selected = bool(prop.get("selected", False))
    if geom.geom_type == "LineString" and (not geom.is_empty):
        items.append({"traj_id": tid, "selected": selected, "geom": geom})
    elif geom.geom_type == "MultiLineString":
        for i, g in enumerate(getattr(geom, "geoms", [])):
            if g.is_empty:
                continue
            items.append({"traj_id": f"{tid}#{i}" if tid else f"line#{i}", "selected": selected, "geom": g})

if not items:
    print("ERROR: no support traj lines for road_id =", road_id)
    if road_counts:
        print("available road_id counts:")
        for rid, cnt in sorted(road_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:20]:
            print(f"  {rid}: {cnt}")
    raise SystemExit(1)

n = len(items)
mids = []
for it in items:
    mid_xy = safe_mid_xy(it["geom"])
    if mid_xy is None:
        continue
    mids.append(mid_xy)
if len(mids) != n:
    print("ERROR: failed to compute midpoint for some support lines")
    raise SystemExit(1)
mids_arr = np.asarray(mids, dtype=np.float64)

if n < 4:
    cluster_count = 1
    cluster_sizes = [n]
    main_cluster_id = 0
    main_cluster_ratio = 1.0
    sep_est = 0.0
    labels_all = [0 for _ in range(n)]
else:
    use_n = min(n, 10)
    mids_use = mids_arr[:use_n, :]
    dm = np.linalg.norm(mids_use[:, None, :] - mids_use[None, :, :], axis=2)
    medoid_idx = int(np.argmin(np.sum(dm, axis=1)))
    ref = mids_use[medoid_idx]
    radial_use = np.linalg.norm(mids_use - ref[None, :], axis=1)
    labels_use, centers = cluster_1d(radial_use, tol=max(1.0, float(sep_m) * 0.45))
    if len(centers) < 2:
        cluster_count = 1
        cluster_sizes = [n]
        main_cluster_id = 0
        main_cluster_ratio = 1.0
        sep_est = 0.0
        labels_all = [0 for _ in range(n)]
    else:
        sep_est = float(max(centers) - min(centers))
        radial_all = np.linalg.norm(mids_arr - ref[None, :], axis=1)
        labels_all = []
        cluster_sizes = [0 for _ in centers]
        for v in radial_all:
            dif = [abs(float(v) - float(c)) for c in centers]
            cid = int(np.argmin(np.asarray(dif, dtype=np.float64)))
            labels_all.append(cid)
            cluster_sizes[cid] += 1
        cluster_count = int(len(centers))
        main_cluster_id = int(np.argmax(np.asarray(cluster_sizes, dtype=np.int64)))
        main_cluster_ratio = float(cluster_sizes[main_cluster_id] / max(1, n))

multi = bool(cluster_count > 1 and sep_est > float(sep_m))
cluster_members: dict[int, list[str]] = defaultdict(list)
cluster_selected: dict[int, int] = defaultdict(int)
for i, it in enumerate(items):
    cid = int(labels_all[i]) if i < len(labels_all) else 0
    tid = str(it.get("traj_id") or f"traj_{i}")
    cluster_members[cid].append(tid)
    if bool(it.get("selected", False)):
        cluster_selected[cid] += 1

print("=== Step1 Multi Corridor Evidence ===")
print("patch_out =", patch_out)
print("road_id =", road_id)
print("hard_hint =", hard_hint)
print("support_line_count =", n)
print("sep_threshold_m =", float(sep_m))
print("cluster_count =", cluster_count)
print("cluster_sizes =", cluster_sizes)
print("main_cluster_id =", main_cluster_id)
print("main_cluster_ratio =", round(float(main_cluster_ratio), 3))
print("cluster_sep_m_est =", round(float(sep_est), 3))
print("multi_detected =", multi)
print("")
for cid in sorted(cluster_members.keys()):
    tids = cluster_members[cid]
    sample = ",".join(tids[:8])
    if len(tids) > 8:
        sample = sample + ",..."
    print(
        f"cluster_{cid}: lines={len(tids)} selected={int(cluster_selected.get(cid, 0))} "
        f"traj_ids_sample={sample}"
    )
PY

