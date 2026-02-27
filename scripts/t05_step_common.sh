#!/usr/bin/env bash
set -euo pipefail

t05_repo_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$script_dir/.." && pwd
}

t05_default_out_root() {
  local repo_root="$1"
  printf "%s/outputs/_work/t05_topology_between_rc" "$repo_root"
}

t05_python_bin() {
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
  return 1
}

t05_make_run_id() {
  printf "t05_%s" "$(date +%Y%m%d_%H%M%S)"
}

t05_patch_out_dir() {
  local out_root="$1"
  local run_id="$2"
  local patch_id="$3"
  printf "%s/%s/patches/%s" "$out_root" "$run_id" "$patch_id"
}

t05_step_dir() {
  local out_root="$1"
  local run_id="$2"
  local patch_id="$3"
  local step_name="$4"
  printf "%s/%s/patches/%s/%s" "$out_root" "$run_id" "$patch_id" "$step_name"
}

t05_write_state() {
  local py="$1"
  local state_path="$2"
  local step="$3"
  local ok="$4"
  local reason="$5"
  local run_id="$6"
  local patch_id="$7"
  local data_root="$8"
  local out_root="$9"
  shift 9
  local extra_json="${1:-{}}"
  "$py" - "$state_path" "$step" "$ok" "$reason" "$run_id" "$patch_id" "$data_root" "$out_root" "$extra_json" <<'PY'
import json
import sys
from datetime import datetime
state_path, step, ok, reason, run_id, patch_id, data_root, out_root, extra_json = sys.argv[1:]
try:
    extra = json.loads(extra_json)
except Exception:
    extra = {}
payload = {
    "step": step,
    "ok": bool(int(ok)),
    "reason": reason,
    "run_id": run_id,
    "patch_id": patch_id,
    "data_root": data_root,
    "out_root": out_root,
    "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
}
if isinstance(extra, dict):
    payload.update(extra)
with open(state_path, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=True, indent=2)
    f.write("\n")
PY
}

t05_detect_hard_reason() {
  local py="$1"
  local gate_json="$2"
  local reason_csv="$3"
  "$py" - "$gate_json" "$reason_csv" <<'PY'
import json
import sys
gate_path, reason_csv = sys.argv[1:]
reasons = {r.strip() for r in reason_csv.split(",") if r.strip()}
try:
    with open(gate_path, "r", encoding="utf-8") as f:
        gate = json.load(f)
except Exception:
    print("")
    raise SystemExit(0)
for bp in gate.get("hard_breakpoints") or []:
    reason = str(bp.get("reason") or "")
    if reason in reasons:
        print(reason)
        raise SystemExit(0)
print("")
PY
}
