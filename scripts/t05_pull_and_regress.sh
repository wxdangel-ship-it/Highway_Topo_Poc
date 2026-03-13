#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

RUN_ID="${1:-t05_pull_regress_$(date +%Y%m%d_%H%M%S)}"
DATA_ROOT="${2:-/mnt/d/TestData/highway_topo_poc_data}"
OUT_ROOT="${3:-/mnt/d/Work/Highway_Topo_Poc/outputs/_work/t05_topology_between_rc_v2}"

cd "${REPO_ROOT}"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "${CURRENT_BRANCH}" == "HEAD" ]]; then
  echo "detached_head_not_supported" >&2
  exit 1
fi

UPSTREAM_REF="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
if [[ -z "${UPSTREAM_REF}" ]]; then
  echo "missing_upstream_for_branch:${CURRENT_BRANCH}" >&2
  echo "hint: git branch --set-upstream-to origin/${CURRENT_BRANCH} ${CURRENT_BRANCH}" >&2
  exit 1
fi

UPSTREAM_REMOTE="${UPSTREAM_REF%%/*}"
UPSTREAM_BRANCH="${UPSTREAM_REF#*/}"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "dirty_worktree_blocked" >&2
  echo "hint: commit/stash/clean local changes before pull --ff-only" >&2
  exit 1
fi

echo "[GIT] branch=${CURRENT_BRANCH} upstream=${UPSTREAM_REF}"
git fetch "${UPSTREAM_REMOTE}" "${UPSTREAM_BRANCH}"

if ! git merge-base --is-ancestor HEAD FETCH_HEAD; then
  echo "non_fast_forward_blocked" >&2
  echo "hint: local branch has diverged from ${UPSTREAM_REF}; resolve manually" >&2
  exit 1
fi

git pull --ff-only "${UPSTREAM_REMOTE}" "${UPSTREAM_BRANCH}"
echo "[GIT] pulled_to=$(git rev-parse HEAD)"

bash "${SCRIPT_DIR}/t05_regress_modified_pairs.sh" "${RUN_ID}" "${DATA_ROOT}" "${OUT_ROOT}"
