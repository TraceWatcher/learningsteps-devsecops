#!/usr/bin/env bash
set -euo pipefail
umask 077

MODE="${1:-}"
SCENARIO="${2:-success}"

usage() {
  echo "Usage:"
  echo "  $0 --plan"
  echo "  $0 --test {success|transport-fails|grant-fails|restore-fails|cleanup-fails}"
  echo "Live Azure execution is disabled."
}

if [[ "$MODE" != "--plan" && "$MODE" != "--test" ]]; then
  usage >&2
  exit 2
fi

if [[ "$MODE" == "--test" ]]; then
  [[ $# -eq 2 ]] || { usage >&2; exit 2; }
  case "$SCENARIO" in
    success|transport-fails|grant-fails|restore-fails|cleanup-fails) ;;
    *) usage >&2; exit 2 ;;
  esac
else
  [[ $# -eq 1 ]] || { usage >&2; exit 2; }
fi

STEPS=(
  "Validate recovery VM and PostgreSQL target"
  "Transfer AGE-encrypted PostgreSQL password"
  "Install and verify remote Python restore files"
  "Grant temporary Key Vault Secrets Officer role"
  "Execute remote restore via Azure Run Command"
  "Verify restored secret version and value"
  "Remove temporary RBAC assignment"
  "Verify Azure RBAC cleanup"
)

if [[ "$MODE" == "--plan" ]]; then
  echo "LearningSteps Key Vault Recovery"
  echo "================================"
  for i in "${!STEPS[@]}"; do
    printf '[%d/%d] %s\n' \
      "$((i + 1))" "${#STEPS[@]}" "${STEPS[$i]}"
  done
  echo "PLAN ONLY: No Azure operations executed."
  exit 0
fi

# The test backend cannot invoke Azure commands.
# These operations will later be wired to the existing
# guarded transport, RBAC, and remote-restore scripts.

test_operation() {
  local step="$1"

  echo "MOCK: $step"

  case "$SCENARIO:$step" in
    transport-fails:transport)
      return 21 ;;
    grant-fails:grant)
      return 22 ;;
    restore-fails:restore)
      return 23 ;;
    cleanup-fails:cleanup)
      return 24 ;;
  esac

  return 0
}

GRANT_ATTEMPTED=0
CLEANUP_ATTEMPTED=0
CLEANUP_RC=0

cleanup() {
  if [[ "$GRANT_ATTEMPTED" -eq 0 ]]; then
    echo "INFO: No RBAC grant attempted"
    return 0
  fi

  if [[ "$CLEANUP_ATTEMPTED" -eq 1 ]]; then
    return "$CLEANUP_RC"
  fi

  CLEANUP_ATTEMPTED=1
  echo "[CLEANUP] Removing temporary RBAC assignment"

  if test_operation cleanup; then
    CLEANUP_RC=0
    echo "PASS: RBAC cleanup confirmed"
  else
    CLEANUP_RC=$?
    echo "CRITICAL: RBAC cleanup not confirmed" >&2
    echo "STOP: Manual reconciliation required" >&2
  fi

  return "$CLEANUP_RC"
}

finish() {
  local original_rc="$1"

  trap - EXIT INT TERM

  if cleanup; then
    if [[ "$original_rc" -ne 0 ]]; then
      echo "FAILED: Recovery aborted; cleanup succeeded" >&2
      exit "$original_rc"
    fi

    echo "PASS: Recovery and cleanup completed"
    exit 0
  fi

  echo "CRITICAL: Recovery security state unresolved" >&2
  exit 90
}

on_exit() {
  local rc=$?
  finish "$rc"
}

trap on_exit EXIT

# A signal must not be mistaken for successful recovery.
trap 'exit 130' INT
trap 'exit 143' TERM

echo "LearningSteps Recovery – MOCK MODE"
echo "Scenario: $SCENARIO"

test_operation preflight
test_operation transport
test_operation install

# From this point onward, a grant may exist even if
# the grant operation returns an error.
GRANT_ATTEMPTED=1
test_operation grant

test_operation restore
test_operation verify

# EXIT trap handles RBAC cleanup for success and failure.
