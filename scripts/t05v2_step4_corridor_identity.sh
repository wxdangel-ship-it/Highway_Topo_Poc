#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/t05v2_step_common.sh"

REPO_ROOT="$(t05v2_repo_root)"
t05v2_setup_pythonpath "$REPO_ROOT"
DATA_ROOT=""
PATCH_ID=""
RUN_ID=""
OUT_ROOT="$(t05v2_default_out_root "$REPO_ROOT")"
DEBUG=0
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --data_root) DATA_ROOT="$2"; shift 2 ;;
    --patch_id) PATCH_ID="$2"; shift 2 ;;
    --run_id) RUN_ID="$2"; shift 2 ;;
    --out_root) OUT_ROOT="$2"; shift 2 ;;
    --debug) DEBUG=1; shift ;;
    --force) FORCE=1; shift ;;
    *) echo "ERROR: unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$DATA_ROOT" ] || [ -z "$PATCH_ID" ] || [ -z "$RUN_ID" ]; then
  echo "ERROR: --data_root --patch_id --run_id are required" >&2
  exit 2
fi

PY="$(t05v2_python_bin "$REPO_ROOT")"
CMD=("$PY" -m highway_topo_poc.modules.t05_topology_between_rc_v2.run --data_root "$DATA_ROOT" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --out_root "$OUT_ROOT" --stage step4_corridor_identity)
if [ "$DEBUG" = "1" ]; then
  CMD+=(--debug)
fi
if [ "$FORCE" = "1" ]; then
  CMD+=(--force)
fi
"${CMD[@]}"
