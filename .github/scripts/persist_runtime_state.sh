#!/usr/bin/env bash
set -euo pipefail

BRANCH="${VICTUS_RUNTIME_STATE_BRANCH:-scanner-runtime-state}"

if [ "$#" -eq 0 ]; then
  echo "No runtime files requested."
  exit 0
fi

TMP_DIR="$(mktemp -d)"
STATE_WORKTREE="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}" "${STATE_WORKTREE}"' EXIT

COPIED=0
for file in "$@"; do
  if [ -f "${file}" ]; then
    mkdir -p "${TMP_DIR}/$(dirname "${file}")"
    cp "${file}" "${TMP_DIR}/${file}"
    COPIED=1
  else
    echo "Skipping missing runtime file ${file}."
  fi
done

if [ "${COPIED}" -eq 0 ]; then
  echo "No runtime state changes to save."
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

if git fetch --quiet origin "${BRANCH}" 2>/dev/null; then
  git worktree add --quiet --detach "${STATE_WORKTREE}" "origin/${BRANCH}"
else
  git worktree add --quiet --detach "${STATE_WORKTREE}" HEAD
  git -C "${STATE_WORKTREE}" switch --quiet --orphan "${BRANCH}"
  git -C "${STATE_WORKTREE}" rm -r --quiet --ignore-unmatch .
fi

for file in "$@"; do
  if [ -f "${TMP_DIR}/${file}" ]; then
    mkdir -p "${STATE_WORKTREE}/$(dirname "${file}")"
    cp "${TMP_DIR}/${file}" "${STATE_WORKTREE}/${file}"
  fi
done

git -C "${STATE_WORKTREE}" add -A
if git -C "${STATE_WORKTREE}" diff --cached --quiet; then
  echo "No runtime state changes to save."
  exit 0
fi

git -C "${STATE_WORKTREE}" commit -m "Update runtime scanner state"
for attempt in 1 2 3; do
  if git -C "${STATE_WORKTREE}" push origin "HEAD:${BRANCH}"; then
    echo "Runtime state saved to ${BRANCH}."
    exit 0
  fi

  echo "::warning::Runtime state push failed on attempt ${attempt}; refreshing ${BRANCH}."
  if git -C "${STATE_WORKTREE}" fetch --quiet origin "${BRANCH}" 2>/dev/null; then
    git -C "${STATE_WORKTREE}" rebase "origin/${BRANCH}" || {
      git -C "${STATE_WORKTREE}" rebase --abort || true
      echo "::error::Could not rebase runtime state after alerts/report were sent."
      exit 1
    }
  fi
done

echo "::error::Could not persist runtime state after retries. Alerts/report were already sent."
exit 1
