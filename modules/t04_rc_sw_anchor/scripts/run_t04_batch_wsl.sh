#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  run_t04_batch_wsl.sh \
    --data_root /mnt/d/TestData/highway_topo_poc_data/normal \
    --global_node_path /mnt/d/TestData/global/RCSDNode.geojson \
    --global_road_path /mnt/d/TestData/global/RCSDRoad.geojson \
    [--cases_file modules/t04_rc_sw_anchor/scripts/batch_cases_example.txt] \
    [--case 2855795596742991:503176747,504381536]... \
    [--out_root outputs/_work/t04_rc_sw_anchor] \
    [--python ./.venv/bin/python] \
    [--dry_run] \
    [--set key=value]...

Input mode:
1) --cases_file: one case per line, format `patch_id:nodeid1,nodeid2,...`
2) --case: repeatable inline mapping, same format as above
3) --cases_file + --case can be mixed

Notes:
- Empty lines and lines starting with # in cases_file are ignored.
- Node IDs can be separated by comma/space/tab on the right side.
- Runs global_focus mode for each patch and writes outputs under out_root.
USAGE
}

DATA_ROOT=""
GLOBAL_NODE_PATH=""
GLOBAL_ROAD_PATH=""
CASES_FILE=""
OUT_ROOT="outputs/_work/t04_rc_sw_anchor"
PY=""
DRY_RUN="false"
SET_ITEMS=()
CASE_ITEMS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --data_root)
      DATA_ROOT="$2"; shift 2 ;;
    --global_node_path)
      GLOBAL_NODE_PATH="$2"; shift 2 ;;
    --global_road_path)
      GLOBAL_ROAD_PATH="$2"; shift 2 ;;
    --cases_file)
      CASES_FILE="$2"; shift 2 ;;
    --case)
      CASE_ITEMS+=("$2"); shift 2 ;;
    --out_root)
      OUT_ROOT="$2"; shift 2 ;;
    --python)
      PY="$2"; shift 2 ;;
    --dry_run)
      DRY_RUN="true"; shift 1 ;;
    --set)
      SET_ITEMS+=("$2"); shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 2 ;;
  esac
done

if [[ -z "$DATA_ROOT" || -z "$GLOBAL_NODE_PATH" || -z "$GLOBAL_ROAD_PATH" ]]; then
  echo "Missing required args." >&2
  usage
  exit 2
fi

if [[ -z "$CASES_FILE" && "${#CASE_ITEMS[@]}" -eq 0 ]]; then
  echo "Either --cases_file or --case must be provided." >&2
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

if [[ -n "$CASES_FILE" && ! -f "$CASES_FILE" ]]; then
  echo "cases_file not found: $CASES_FILE" >&2
  exit 2
fi

mkdir -p "$OUT_ROOT"

TS="$(date +%Y%m%d_%H%M%S)"
BATCH_ID="t04_batch_${TS}"
BATCH_DIR="${OUT_ROOT}/_batch"
mkdir -p "$BATCH_DIR"
MANIFEST_PATH="${BATCH_DIR}/${BATCH_ID}_manifest.tsv"

echo -e "idx\tpatch_id\tnode_ids\trun_id\tstatus\tout_dir" > "$MANIFEST_PATH"

idx=0
ok=0
fail=0

process_case_line() {
  local raw_line="$1"
  local line patch_id rhs node_ids patch_dir run_id out_dir status kv

  line="$(echo "$raw_line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  [[ -z "$line" ]] && return 0
  [[ "$line" =~ ^# ]] && return 0

  if [[ "$line" != *:* ]]; then
    echo "Skip invalid line (missing ':'): $line" >&2
    return 0
  fi

  patch_id="${line%%:*}"
  rhs="${line#*:}"
  patch_id="$(echo "$patch_id" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  rhs="$(echo "$rhs" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"

  if [[ -z "$patch_id" || -z "$rhs" ]]; then
    echo "Skip invalid line (empty patch_id/node_ids): $line" >&2
    return 0
  fi

  node_ids="$(echo "$rhs" | tr ' \t' ',' | tr -s ',' | sed 's/^,//; s/,$//')"
  if [[ -z "$node_ids" ]]; then
    echo "Skip invalid line (normalized node_ids empty): $line" >&2
    return 0
  fi

  patch_dir="${DATA_ROOT%/}/${patch_id}"
  run_id="t04_focus_${patch_id}_${TS}_$(printf '%03d' "$idx")"
  out_dir="${OUT_ROOT%/}/${run_id}"

  cmd=(
    "$PY" -m highway_topo_poc.modules.t04_rc_sw_anchor
    --mode global_focus
    --patch_dir "$patch_dir"
    --out_root "$OUT_ROOT"
    --run_id "$run_id"
    --global_node_path "$GLOBAL_NODE_PATH"
    --global_road_path "$GLOBAL_ROAD_PATH"
    --focus_node_ids "$node_ids"
    --src_crs auto
    --dst_crs EPSG:3857
    --node_src_crs auto
    --road_src_crs auto
    --divstrip_src_crs auto
    --drivezone_src_crs auto
    --traj_src_crs auto
    --pointcloud_crs auto
  )

  for kv in "${SET_ITEMS[@]}"; do
    cmd+=(--set "$kv")
  done

  echo "[$idx] patch_id=$patch_id node_ids=$node_ids"
  echo "      run_id=$run_id"

  status="ok"
  if [[ "$DRY_RUN" == "true" ]]; then
    printf '      CMD: '
    printf '%q ' "${cmd[@]}"
    printf '\n'
  else
    if "${cmd[@]}"; then
      ok=$((ok + 1))
    else
      status="fail"
      fail=$((fail + 1))
      echo "      ERROR: run failed for patch_id=$patch_id" >&2
    fi
  fi

  echo -e "${idx}\t${patch_id}\t${node_ids}\t${run_id}\t${status}\t${out_dir}" >> "$MANIFEST_PATH"
  idx=$((idx + 1))
}

if [[ -n "$CASES_FILE" ]]; then
  while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
    process_case_line "$raw_line"
  done < "$CASES_FILE"
fi

for raw_line in "${CASE_ITEMS[@]}"; do
  process_case_line "$raw_line"
done

echo
echo "Batch finished:"
echo "  total=${idx} ok=${ok} fail=${fail} dry_run=${DRY_RUN}"
echo "  manifest=${MANIFEST_PATH}"

if [[ "$DRY_RUN" == "false" && "$fail" -gt 0 ]]; then
  exit 1
fi
