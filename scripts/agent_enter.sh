#!/usr/bin/env bash
set -e

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$ROOT" ]; then
  echo "[BLOCK] Not inside a git repository."
  exit 2
fi

cd "$ROOT"
pwd
git rev-parse --show-toplevel
git status -sb
