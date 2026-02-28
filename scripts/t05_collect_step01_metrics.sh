#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/t05_step_common.sh"

REPO_ROOT="$(t05_repo_root)"
OUT_ROOT="$(t05_default_out_root "$REPO_ROOT")"
RUN_ID=""
PATCH_IDS=""

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

PY="$(t05_python_bin "$REPO_ROOT")"
IFS=',' read -r -a PATCH_ARR <<< "$PATCH_IDS"

"$PY" - "$OUT_ROOT" "$RUN_ID" "${PATCH_ARR[@]}" <<'PY'
import json
import sys
from pathlib import Path

out_root = Path(sys.argv[1])
run_id = sys.argv[2]
patches = [p.strip() for p in sys.argv[3:] if p.strip()]

keys = [
    "xsec_gate_len_src_p90",
    "xsec_gate_len_dst_p90",
    "xsec_gate_fallback_src_count",
    "xsec_gate_fallback_dst_count",
    "traj_drop_count_by_drivezone",
    "drivezone_fallback_used_count",
    "step1_corridor_count_p90",
    "step1_main_corridor_ratio_p50",
]

rows = []
for patch_id in patches:
    metrics_path = out_root / run_id / "patches" / patch_id / "metrics.json"
    if not metrics_path.is_file():
        rows.append({"patch_id": patch_id, "missing_metrics": True})
        continue
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except Exception as exc:
        rows.append({"patch_id": patch_id, "metrics_parse_error": str(exc)})
        continue
    row = {"patch_id": patch_id}
    for k in keys:
        row[k] = metrics.get(k)
    rows.append(row)

print(json.dumps({"run_id": run_id, "rows": rows}, ensure_ascii=True, indent=2))
PY
