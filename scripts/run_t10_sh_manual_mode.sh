#!/usr/bin/env bash
set -euo pipefail

# T10 manual-mode WSL runner
# dataset dir and mainnodeid(s) must be provided explicitly by caller.
# Main outputs: <repo>/outputs/_work/T10/sh_manual_mode/
# Optional --manual-override may be a single JSON file or a directory containing <mainnodeid>.json files.
# --compute-buffer-m is reserved for future geometry compute acceleration only; it does not change truth selection.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DATASET_DIR=""
OUTPUT_ROOT="${REPO_ROOT}/outputs/_work/T10/sh_manual_mode"
COMPUTE_BUFFER_M="200"
MANUAL_OVERRIDE=""
MAINNODEIDS=()
VALIDATE_OVERRIDE="1"

print_help() {
  cat <<'EOF'
Usage:
  bash scripts/run_t10_sh_manual_mode.sh [options]

Options:
  --dataset-dir <path>            Required. WSL dataset dir containing RCSDNode / RCSDRoad
  --mainnodeid <id...>            Required. One or more mainnodeid values; also accepts comma-separated items
  --mainnodeids <id...>           Legacy plural alias, kept for compatibility
  --manual-override <path>        Optional override JSON file or per-mainnodeid override directory
  --output-root <path>            Output root under repo outputs
  --compute-buffer-m <meters>     Reserved compute buffer for future optimization only
  --skip-override-validation      Skip override validator before rerun
  --help                          Show this help

Examples:
  bash scripts/run_t10_sh_manual_mode.sh --dataset-dir /mnt/d/TestData/highway_topo_poc_data/Intersection/SH --mainnodeid 12113465
  bash scripts/run_t10_sh_manual_mode.sh --dataset-dir /mnt/d/TestData/highway_topo_poc_data/Intersection/SH --mainnodeid 12113465 12113466
  bash scripts/run_t10_sh_manual_mode.sh --dataset-dir /mnt/d/TestData/highway_topo_poc_data/Intersection/SH --mainnodeid 12113465 --manual-override /mnt/d/override/12113465.json
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dataset-dir)
      DATASET_DIR="$2"
      shift 2
      ;;
    --mainnodeid|--mainnodeids)
      shift
      MAINNODEIDS=()
      while [[ $# -gt 0 && "${1}" != --* ]]; do
        MAINNODEIDS+=("$1")
        shift
      done
      ;;
    --manual-override)
      MANUAL_OVERRIDE="$2"
      shift 2
      ;;
    --output-root)
      OUTPUT_ROOT="$2"
      shift 2
      ;;
    --compute-buffer-m)
      COMPUTE_BUFFER_M="$2"
      shift 2
      ;;
    --skip-override-validation)
      VALIDATE_OVERRIDE="0"
      shift
      ;;
    --help|-h)
      print_help
      exit 0
      ;;
    *)
      echo "unknown_argument:$1" >&2
      print_help >&2
      exit 1
      ;;
  esac
done

if [[ -z "${DATASET_DIR}" ]]; then
  echo "missing_required_argument:--dataset-dir" >&2
  print_help >&2
  exit 1
fi

if [[ ${#MAINNODEIDS[@]} -eq 0 ]]; then
  echo "missing_required_argument:--mainnodeid" >&2
  print_help >&2
  exit 1
fi

if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

CMD=(
  "${PYTHON_BIN}"
  -m
  highway_topo_poc.modules.t10_complex_intersection_modeling.cli
  --dataset-dir "${DATASET_DIR}"
  --output-dir "${OUTPUT_ROOT}"
  --compute-buffer-m "${COMPUTE_BUFFER_M}"
  --mainnodeid
)
CMD+=("${MAINNODEIDS[@]}")

if [[ -n "${MANUAL_OVERRIDE}" ]]; then
  CMD+=(--manual-override "${MANUAL_OVERRIDE}")
  if [[ "${VALIDATE_OVERRIDE}" == "1" ]]; then
    CMD+=(--validate-override)
  fi
fi

printf 'Running T10 SH manual mode:\n'
printf '  dataset_dir=%s\n' "${DATASET_DIR}"
printf '  mainnodeid=%s\n' "${MAINNODEIDS[*]}"
printf '  output_root=%s\n' "${OUTPUT_ROOT}"
printf '  compute_buffer_m=%s\n' "${COMPUTE_BUFFER_M}"
if [[ -n "${MANUAL_OVERRIDE}" ]]; then
  printf '  manual_override=%s\n' "${MANUAL_OVERRIDE}"
fi

"${CMD[@]}"
