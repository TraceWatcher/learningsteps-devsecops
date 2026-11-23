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

if [[ "$MODE" != "--plan" &&
      "$MODE" != "--test" &&
      "$MODE" != "--integration-test" ]]; then
  usage >&2
  exit 2
fi

if [[ "$MODE" == "--integration-test" ]]; then
  [[ $# -eq 1 ]] || {
    usage >&2
    exit 2
  }

  # Require an explicitly selected isolated test directory.
  [[ -n "${LS_INTEGRATION_ROOT:-}" &&
     "${LS_INTEGRATION_ROOT:0:1}" == "/" &&
     -d "$LS_INTEGRATION_ROOT" &&
     ! -L "$LS_INTEGRATION_ROOT" ]] || {
    echo "ERROR: Isolated integration directory required" >&2
    exit 2
  }

  INTEGRATION_ROOT="$LS_INTEGRATION_ROOT"
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


# Prevent concurrent recovery runs on this host.
# Keep the file descriptor open until the process exits.
LOCK_DIR="$HOME/learningsteps-recovery"

if [[ ! -d "$LOCK_DIR" ||
      -L "$LOCK_DIR" ]]; then
  echo "ERROR: Unsafe recovery lock directory" >&2
  exit 1
fi

if [[ "$(stat -c %u "$LOCK_DIR")" != "$(id -u)" ||
      "$(stat -c %a "$LOCK_DIR")" != "700" ]]; then
  echo "ERROR: Unsafe recovery lock directory permissions" >&2
  exit 1
fi

LOCK_FILE="$LOCK_DIR/.recovery.lock"

if [[ -e "$LOCK_FILE" || -L "$LOCK_FILE" ]]; then
  if [[ -L "$LOCK_FILE" ||
        ! -f "$LOCK_FILE" ||
        "$(stat -c %u "$LOCK_FILE")" != "$(id -u)" ||
        "$(stat -c %a "$LOCK_FILE")" != "600" ]]; then
    echo "ERROR: Unsafe recovery lock file" >&2
    exit 1
  fi
fi

exec 8>>"$LOCK_FILE"

if ! flock -n 8; then
  echo "ERROR: Another recovery process is running" >&2
  exit 75
fi

echo "PASS: Exclusive local recovery lock acquired"


# The test backend cannot invoke Azure commands.
# These operations will later be wired to the existing
# guarded transport, RBAC, and remote-restore scripts.

mock_operation() {
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


integration_operation() {
  local operation="$1"
  local script=""

  case "$operation" in
    preflight)
      script="prepare-keyvault-transport.sh"
      ;;
    transport)
      script="transport-keyvault-password.sh"
      ;;
    install|restore)
      script="run-keyvault-recovery-command.sh"
      ;;
    grant|cleanup)
      script="recovery-keyvault-rbac.sh"
      ;;
    verify)
      # The remote restore already verifies the exact
      # secret version and password before returning 0.
      echo "PASS: Restore verification is part of remote execution"
      return 0
      ;;
    *)
      echo "ERROR: Unknown operation" >&2
      return 2
      ;;
  esac

  local target="$INTEGRATION_ROOT/$script"

  [[ -f "$target" && ! -L "$target" && -x "$target" ]] || {
    echo "ERROR: Integration script unavailable: $script" >&2
    return 1
  }

  echo "[INTEGRATION] $operation"

  case "$operation" in
    transport)
      "$target" --transfer
      ;;

    install|restore)
      local payload
      local command_mode

      local payload_dir="$INTEGRATION_ROOT/payloads"

      [[ -d "$payload_dir" &&
         ! -L "$payload_dir" ]] || {
        echo "ERROR: Integration payload directory missing" >&2
        return 1
      }

      if [[ "$operation" == "install" ]]; then
        payload="$payload_dir/install.sh"
        command_mode="--install"

        [[ ! -e "$payload" && ! -L "$payload" ]] || {
          echo "ERROR: Installation payload already exists" >&2
          return 1
        }

        python3 \
          "$INTEGRATION_ROOT/build-keyvault-install-payload.py" \
          --output "$payload"
      else
        payload="$payload_dir/restore.sh"
        command_mode="--restore"

        [[ ! -e "$payload" && ! -L "$payload" ]] || {
          echo "ERROR: Restore payload already exists" >&2
          return 1
        }

        python3 \
          "$INTEGRATION_ROOT/build-keyvault-restore-payload.py" \
          --state "$HOME/learningsteps-recovery/temporary-keyvault-rbac.json" \
          --private-ip "${LS_TEST_PRIVATE_IP:?}" \
          --output "$payload"
      fi

      bash -n "$payload"

      [[ -n "${LS_MOCK_AZ:-}" &&
         -x "$LS_MOCK_AZ" ]] || {
        echo "ERROR: Offline Azure mock required" >&2
        return 1
      }

      "$target" --offline-test "$command_mode" "$payload"
      ;;

    grant)
      "$target" grant
      ;;
    cleanup)
      "$target" cleanup-auto
      ;;
    *)
      "$target"
      ;;
  esac
}

run_operation() {
  local operation="$1"

  case "$MODE" in
    --test)
      mock_operation "$operation"
      ;;
    --integration-test)
      integration_operation "$operation"
      ;;
    *)
      echo "ERROR: Live recovery backend is disabled" >&2
      return 2
      ;;
  esac
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

  if run_operation cleanup; then
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

echo "LearningSteps Recovery – $MODE"
echo "Scenario: $SCENARIO"

run_operation preflight
run_operation transport
run_operation install

# From this point onward, a grant may exist even if
# the grant operation returns an error.
GRANT_ATTEMPTED=1
run_operation grant

run_operation restore
run_operation verify

# EXIT trap handles RBAC cleanup for success and failure.
