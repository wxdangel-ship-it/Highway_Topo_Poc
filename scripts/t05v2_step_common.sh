#!/usr/bin/env bash
set -euo pipefail

t05v2_repo_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$script_dir/.." && pwd
}

t05v2_default_out_root() {
  local repo_root="$1"
  printf "%s/outputs/_work/t05_topology_between_rc_v2" "$repo_root"
}

t05v2_python_bin() {
  local repo_root="$1"
  if [ -n "${PYTHON_BIN:-}" ]; then
    printf "%s" "$PYTHON_BIN"
    return 0
  fi
  if [ -x "$repo_root/.venv/bin/python" ]; then
    printf "%s" "$repo_root/.venv/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi
  return 1
}

t05v2_setup_pythonpath() {
  local repo_root="$1"
  export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"
}

t05v2_make_run_id() {
  printf "t05v2_%s" "$(date +%Y%m%d_%H%M%S)"
}

t05v2_step_state() {
  local out_root="$1"
  local run_id="$2"
  local patch_id="$3"
  local step_name="$4"
  local dir_name="$step_name"
  case "$step_name" in
    step1_input_frame) dir_name="step1" ;;
    step2_segment) dir_name="step2" ;;
    step3_witness) dir_name="step3" ;;
    step4_corridor_identity) dir_name="step4" ;;
    step5_slot_mapping) dir_name="step5" ;;
    step6_build_road) dir_name="step6" ;;
  esac
  printf "%s/%s/patches/%s/%s/step_state.json" "$out_root" "$run_id" "$patch_id" "$dir_name"
}

t05v2_state_ok() {
  local py="$1"
  local state_path="$2"
  "$py" - "$state_path" <<'PY'
import json
import sys
path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
except Exception:
    print("0")
    raise SystemExit(0)
print("1" if bool(payload.get("ok")) else "0")
PY
}
