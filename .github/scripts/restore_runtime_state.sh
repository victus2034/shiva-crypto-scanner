#!/usr/bin/env bash
set -euo pipefail

BRANCH="${VICTUS_RUNTIME_STATE_BRANCH:-scanner-runtime-state}"

if [ "$#" -eq 0 ]; then
  echo "No runtime files requested."
  exit 0
fi

if ! git fetch --quiet origin "${BRANCH}" 2>/dev/null; then
  echo "Runtime state branch ${BRANCH} does not exist yet."
  exit 0
fi

for file in "$@"; do
  if git cat-file -e "origin/${BRANCH}:${file}" 2>/dev/null; then
    mkdir -p "$(dirname "${file}")"
    git show "origin/${BRANCH}:${file}" > "${file}"
    echo "Restored ${file} from ${BRANCH}."
  else
    echo "No saved runtime state for ${file}."
  fi
done
