#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/run_t04_patch_auto_nodes.sh PATCH_DIR [KIND_MASK] [OUT_ROOT]

Positional:
  PATCH_DIR    Required. Patch directory.
  KIND_MASK    Optional. Node kind mask for auto discovery (default: 65560 = 8|16|65536).
  OUT_ROOT     Optional. Output root (default: outputs/_work/t04_rc_sw_anchor).

Options:
  --kind_mask <int>   Override kind mask (supports decimal/hex like 65560 or 0x10018).
  --out_root <path>   Override output root.
  --python <path>     Python binary (default: ./.venv/bin/python, fallback: python3).
  -h, --help          Show help.

Env fallback:
  KIND_MASK, OUT_ROOT, PYTHON_BIN
USAGE
}

PATCH_DIR=""
KIND_MASK="${KIND_MASK:-65560}"
OUT_ROOT="${OUT_ROOT:-outputs/_work/t04_rc_sw_anchor}"
PY="${PYTHON_BIN:-}"
POSITIONAL=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kind_mask)
      KIND_MASK="$2"; shift 2 ;;
    --out_root)
      OUT_ROOT="$2"; shift 2 ;;
    --python)
      PY="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    --*)
      echo "Unknown option: $1" >&2
      usage
      exit 2 ;;
    *)
      POSITIONAL+=("$1"); shift 1 ;;
  esac
done

if [[ "${#POSITIONAL[@]}" -lt 1 ]]; then
  echo "PATCH_DIR is required." >&2
  usage
  exit 2
fi

PATCH_DIR="${POSITIONAL[0]}"
if [[ "${#POSITIONAL[@]}" -ge 2 ]]; then
  KIND_MASK="${POSITIONAL[1]}"
fi
if [[ "${#POSITIONAL[@]}" -ge 3 ]]; then
  OUT_ROOT="${POSITIONAL[2]}"
fi
if [[ "${#POSITIONAL[@]}" -gt 3 ]]; then
  echo "Too many positional args." >&2
  usage
  exit 2
fi

if [[ -z "$PY" ]]; then
  if [[ -x "./.venv/bin/python" ]]; then
    PY="./.venv/bin/python"
  else
    PY="python3"
  fi
fi

if [[ ! -d "$PATCH_DIR" ]]; then
  echo "patch_dir_not_found: $PATCH_DIR" >&2
  exit 2
fi

VECTOR_DIR="${PATCH_DIR%/}/Vector"
NODE_PRIMARY="${VECTOR_DIR}/RCSDNode.geojson"
NODE_FALLBACK="${VECTOR_DIR}/Node.geojson"
ROAD_PRIMARY="${VECTOR_DIR}/RCSDRoad.geojson"
ROAD_FALLBACK="${VECTOR_DIR}/Road.geojson"

if [[ -f "$NODE_PRIMARY" ]]; then
  GLOBAL_NODE_PATH="$NODE_PRIMARY"
elif [[ -f "$NODE_FALLBACK" ]]; then
  GLOBAL_NODE_PATH="$NODE_FALLBACK"
else
  echo "global_node_path_not_found: ${NODE_PRIMARY} or ${NODE_FALLBACK}" >&2
  exit 2
fi

if [[ -f "$ROAD_PRIMARY" ]]; then
  GLOBAL_ROAD_PATH="$ROAD_PRIMARY"
elif [[ -f "$ROAD_FALLBACK" ]]; then
  GLOBAL_ROAD_PATH="$ROAD_FALLBACK"
else
  echo "global_road_path_not_found: ${ROAD_PRIMARY} or ${ROAD_FALLBACK}" >&2
  exit 2
fi

mkdir -p "$OUT_ROOT"
PATCH_ID="$(basename "$PATCH_DIR")"
TS="$(date +%Y%m%d_%H%M%S)"
RUN_ID="t04_patch_auto_${PATCH_ID}_${TS}_$$"
RUN_DIR="${OUT_ROOT%/}/${RUN_ID}"
mkdir -p "$RUN_DIR"

RESOLVED_TXT="${RUN_DIR}/focus_node_ids_resolved.txt"
RESOLVED_JSON="${RUN_DIR}/focus_node_ids_resolved.json"
DISCOVERY_REPORT_JSON="${RUN_DIR}/node_discovery_report.json"
AUTO_META_JSON="${RUN_DIR}/auto_nodes.meta.json"

"$PY" -m highway_topo_poc.modules.t04_rc_sw_anchor.node_discovery \
  --rcsdnode_path "$GLOBAL_NODE_PATH" \
  --kind_mask "$KIND_MASK" \
  --out_txt "$RESOLVED_TXT" \
  --out_json "$RESOLVED_JSON"

cp "$RESOLVED_JSON" "$DISCOVERY_REPORT_JSON"

AUTO_COUNT="$("$PY" -c 'import json,sys; d=json.load(open(sys.argv[1],encoding="utf-8")); print(int(d.get("selected_count",0)))' "$RESOLVED_JSON")"

"$PY" -c 'import json,sys; rep=json.load(open(sys.argv[1],encoding="utf-8")); out={
  "auto_nodes": True,
  "auto_nodes_count": int(rep.get("selected_count", 0)),
  "kind_mask": int(rep.get("kind_mask", 0)),
  "kind_mask_hex": rep.get("kind_mask_hex"),
  "kind_histogram": rep.get("kind_histogram", {}),
  "id_field_hit_stats": rep.get("id_field_hit_stats", {}),
  "selected_count": int(rep.get("selected_count", 0)),
  "filtered_out_count": int(rep.get("filtered_out_count", 0)),
  "focus_node_ids_file": "focus_node_ids_resolved.txt"
}; json.dump(out, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=2); open(sys.argv[2], "a", encoding="utf-8").write("\n")' \
  "$RESOLVED_JSON" "$AUTO_META_JSON"

if [[ "$AUTO_COUNT" -le 0 ]]; then
  echo "node_discovery_empty_after_filter: kind_mask=${KIND_MASK} patch_dir=${PATCH_DIR}" >&2
  echo "report: ${DISCOVERY_REPORT_JSON}" >&2
  exit 3
fi

cmd=(
  "$PY" -m highway_topo_poc.modules.t04_rc_sw_anchor
  --mode global_focus
  --patch_dir "$PATCH_DIR"
  --out_root "$OUT_ROOT"
  --run_id "$RUN_ID"
  --global_node_path "$GLOBAL_NODE_PATH"
  --global_road_path "$GLOBAL_ROAD_PATH"
  --focus_node_ids_file "$RESOLVED_TXT"
  --src_crs auto
  --dst_crs EPSG:3857
  --node_src_crs auto
  --road_src_crs auto
  --divstrip_src_crs auto
  --drivezone_src_crs auto
  --traj_src_crs auto
  --pointcloud_crs auto
)

"${cmd[@]}"

echo "OK run_dir=${RUN_DIR}"
echo "focus_node_ids=${RESOLVED_TXT}"
echo "focus_report=${RESOLVED_JSON}"
echo "auto_meta=${AUTO_META_JSON}"
