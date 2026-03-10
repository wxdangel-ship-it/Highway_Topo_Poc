#!/usr/bin/env bash
set -euo pipefail

# Pull latest main branch from GitHub, then run the SH WSL script.
# Default branch: main
# Default dataset dir: /mnt/d/TestData/highway_topo_poc_data/Intersection/SH
# Default mainnodeid: 12113465

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REMOTE_NAME="origin"
BRANCH_NAME="main"
RUN_ARGS=()
SKIP_PULL="0"

print_help() {
  cat <<'EOF'
Usage:
  bash scripts/pull_and_run_t10_sh_manual_mode.sh [options] [-- run_args...]

Options:
  --remote <name>                Git remote name, default origin
  --branch <name>                Git branch name, default main
  --skip-pull                    Skip fetch/switch/pull and only run local script
  --help                         Show this help

Everything after `--` is forwarded to:
  bash scripts/run_t10_sh_manual_mode.sh

Examples:
  bash scripts/pull_and_run_t10_sh_manual_mode.sh
  bash scripts/pull_and_run_t10_sh_manual_mode.sh -- --mainnodeids 12113465
  bash scripts/pull_and_run_t10_sh_manual_mode.sh -- --mainnodeids 12113465 12113466 --manual-override /mnt/d/override/12113465.json
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote)
      REMOTE_NAME="$2"
      shift 2
      ;;
    --branch)
      BRANCH_NAME="$2"
      shift 2
      ;;
    --skip-pull)
      SKIP_PULL="1"
      shift
      ;;
    --help|-h)
      print_help
      exit 0
      ;;
    --)
      shift
      RUN_ARGS=("$@")
      break
      ;;
    *)
      RUN_ARGS+=("$1")
      shift
      ;;
  esac
done

cd "${REPO_ROOT}"

if [[ "${SKIP_PULL}" != "1" ]]; then
  git fetch "${REMOTE_NAME}" --prune
  if git ls-remote --exit-code --heads "${REMOTE_NAME}" "${BRANCH_NAME}" >/dev/null 2>&1; then
    if git show-ref --verify --quiet "refs/heads/${BRANCH_NAME}"; then
      git switch "${BRANCH_NAME}"
    else
      git switch -c "${BRANCH_NAME}" --track "${REMOTE_NAME}/${BRANCH_NAME}"
    fi
    git pull --ff-only "${REMOTE_NAME}" "${BRANCH_NAME}"
  else
    echo "remote_branch_not_found:${REMOTE_NAME}/${BRANCH_NAME}" >&2
    exit 1
  fi
fi

bash "${REPO_ROOT}/scripts/run_t10_sh_manual_mode.sh" "${RUN_ARGS[@]}"
