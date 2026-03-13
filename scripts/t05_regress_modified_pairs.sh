#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

RUN_ID="${1:-t05_pair_regress_$(date +%Y%m%d_%H%M%S)}"
DATA_ROOT="${2:-/mnt/d/TestData/highway_topo_poc_data}"
OUT_ROOT="${3:-/mnt/d/Work/Highway_Topo_Poc/outputs/_work/t05_topology_between_rc_v2}"

COMPLEX_PATCH_ID="5417632623039346"
SIMPLE_PATCH_PASS_ID="5417632690143326"
SIMPLE_PATCH_EXPLAIN_ID="5417632690143239"

PAIR_LIST=(
  "5384367610468452:765141"
  "791871:37687913"
  "55353246:37687913"
  "5395717732638194:37687913"
)

cd "${REPO_ROOT}"

PYTHON_BIN=".venv/bin/python"
PAIR_CHECK_SCRIPT="scripts/t05_pair_check.py"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "missing_python:${REPO_ROOT}/${PYTHON_BIN}" >&2
  exit 1
fi

if [[ ! -f "${PAIR_CHECK_SCRIPT}" ]]; then
  echo "missing_pair_check_script:${REPO_ROOT}/${PAIR_CHECK_SCRIPT}" >&2
  exit 1
fi

run_patch() {
  local patch_id="$1"
  echo "[RUN] patch_id=${patch_id} run_id=${RUN_ID}"
  "${PYTHON_BIN}" -m highway_topo_poc.modules.t05_topology_between_rc_v2 \
    --data_root "${DATA_ROOT}" \
    --patch_id "${patch_id}" \
    --run_id "${RUN_ID}" \
    --out_root "${OUT_ROOT}" \
    --stage full
}

print_patch_summary() {
  local patch_id="$1"
  local metrics_path="${OUT_ROOT}/${RUN_ID}/patches/${patch_id}/metrics.json"
  local gate_path="${OUT_ROOT}/${RUN_ID}/patches/${patch_id}/gate.json"
  echo "[SUMMARY] patch_id=${patch_id}"
  "${PYTHON_BIN}" - "${metrics_path}" "${gate_path}" <<'PY'
import json
import sys
from pathlib import Path

metrics = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
gate = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
payload = {
    "patch_id": metrics.get("patch_id"),
    "segment_count": metrics.get("segment_count"),
    "road_count": metrics.get("road_count"),
    "overall_pass": gate.get("overall_pass"),
    "failure_classification_hist": metrics.get("failure_classification_hist", {}),
    "no_geometry_candidate_reason": metrics.get("no_geometry_candidate_reason"),
}
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
}

export_pair_check() {
  local pair_id="$1"
  local pair_file="${OUT_ROOT}/${RUN_ID}/patches/${COMPLEX_PATCH_ID}/debug/pair_checks/${pair_id//:/__}.json"
  mkdir -p "$(dirname "${pair_file}")"
  echo "[PAIR] ${pair_id}"
  "${PYTHON_BIN}" "${PAIR_CHECK_SCRIPT}" \
    --out-root "${OUT_ROOT}" \
    --run-id "${RUN_ID}" \
    --patch-id "${COMPLEX_PATCH_ID}" \
    --pair "${pair_id}" \
    --support-limit 20 | tee "${pair_file}"
}

run_patch "${COMPLEX_PATCH_ID}"
for pair_id in "${PAIR_LIST[@]}"; do
  export_pair_check "${pair_id}"
done

run_patch "${SIMPLE_PATCH_PASS_ID}"
print_patch_summary "${SIMPLE_PATCH_PASS_ID}"

run_patch "${SIMPLE_PATCH_EXPLAIN_ID}"
print_patch_summary "${SIMPLE_PATCH_EXPLAIN_ID}"

echo "[DONE] run_id=${RUN_ID}"
echo "[DONE] complex_patch_dir=${OUT_ROOT}/${RUN_ID}/patches/${COMPLEX_PATCH_ID}"
