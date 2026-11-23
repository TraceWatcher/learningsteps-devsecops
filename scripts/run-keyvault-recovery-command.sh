#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RG="rg-learningsteps-devsecops"
VM="learningsteps-maintenance"
STATE="$HOME/learningsteps-recovery/temporary-keyvault-rbac.json"

# Explicitly select a simulated Azure CLI.
# The real Azure CLI must never be used in offline execution.
OFFLINE=0
AZ_CMD=()

if [[ "${1:-}" == "--offline-test" ]]; then
  OFFLINE=1
  shift

  [[ -n "${LS_MOCK_AZ:-}" &&
     "${LS_MOCK_AZ:0:1}" == "/" &&
     -f "$LS_MOCK_AZ" &&
     -x "$LS_MOCK_AZ" ]] || {
    echo "ERROR: Explicit mock Azure executable required" >&2
    exit 2
  }

  AZ_CMD=("$LS_MOCK_AZ")
else
  AZ_CMD=(az)
fi

MODE="${1:-}"

if [[ $# -ne 2 ||
      ( "$MODE" != "--install" &&
        "$MODE" != "--restore" ) ]]; then
  echo "Usage: $0 {--install|--restore} PAYLOAD_FILE" >&2
  exit 2
fi

PAYLOAD="$2"

[[ -f "$PAYLOAD" && ! -L "$PAYLOAD" ]] || {
  echo "ERROR: Unsafe payload file" >&2
  exit 1
}

[[ -s "$STATE" && ! -L "$STATE" ]] || {
  echo "ERROR: Missing recovery state" >&2
  exit 1
}

# Fail before any Azure Run Command if the original VM
# or an unexpected recovery target is detected.
if [[ "$OFFLINE" -eq 0 ]]; then
  "$ROOT/scripts/check-recovery-vm.sh"
else
  echo "OFFLINE: Original VM checker replaced by mock validation"
fi

EXPECTED="$(python3 - "$STATE" "$MODE" <<'PY'
import json
import sys
import uuid

state_file, mode = sys.argv[1:]

with open(state_file, encoding="utf-8") as f:
    state = json.load(f)

for field in ("vm_id", "principal_id", "recovery_id"):
    uuid.UUID(state[field])

status = state["status"]

if mode == "--install":
    allowed = ("prepared", "granted")
else:
    allowed = ("granted",)

if status not in allowed:
    raise SystemExit(
        "ERROR: Recovery RBAC state does not authorize this operation"
    )

print(state["vm_id"])
print(state["principal_id"])
PY
)"

EXPECTED_VM_ID="$(sed -n '1p' <<< "$EXPECTED")"
EXPECTED_PRINCIPAL="$(sed -n '2p' <<< "$EXPECTED")"

read_vm_identity() {
  "${AZ_CMD[@]}" vm show \
    --resource-group "$RG" \
    --name "$VM" \
    --query '{vmId:vmId,principalId:identity.principalId}' \
    -o json
}

BEFORE="$(read_vm_identity)"

export BEFORE EXPECTED_VM_ID EXPECTED_PRINCIPAL

python3 - <<'PY'
import json
import os

vm = json.loads(os.environ["BEFORE"])

if (
    vm.get("vmId") != os.environ["EXPECTED_VM_ID"]
    or vm.get("principalId") != os.environ["EXPECTED_PRINCIPAL"]
):
    raise SystemExit("ERROR: Recovery VM identity mismatch")

print("PASS: Recovery VM identity verified")
PY

# Restore requires a confirmed Azure RBAC assignment.
# Exit 0 from the RBAC controller is meaningful only
# after the local state was independently checked as granted.
if [[ "$MODE" == "--restore" ]]; then
  echo "[SECURITY] Verifying Azure RBAC assignment"

  "$ROOT/scripts/recovery-keyvault-rbac.sh" status

  echo "PASS: Recovery RBAC state confirmed"
fi

TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT

RESULT_FILE="$TMP/result.json"

if [[ "$OFFLINE" -ne 1 ]]; then
  echo "PLAN: Live Azure Run Command remains disabled"
  exit 0
fi

echo "[OFFLINE] Simulating Azure Run Command"

RUN_RC=0

if "${AZ_CMD[@]}" vm run-command invoke \
  --resource-group "$RG" \
  --name "$VM" \
  --command-id RunShellScript \
  --scripts "@$PAYLOAD" \
  -o json > "$RESULT_FILE"; then
  echo "INFO: Azure CLI returned successfully"
else
  RUN_RC=$?
  echo "ERROR: Run Command invocation failed" >&2
fi

if [[ "$MODE" == "--install" ]]; then
  OPERATION="install"
else
  OPERATION="restore"
fi

VERIFY_RC=0

if [[ "$RUN_RC" -eq 0 ]]; then
  echo "[VERIFY] Checking remote execution result"

  if python3 "$ROOT/scripts/verify-run-command-result.py" \
    --operation "$OPERATION" \
    --result "$RESULT_FILE"; then
    echo "PASS: Remote execution result verified"
  else
    VERIFY_RC=$?
    echo "ERROR: Remote result could not be verified" >&2
  fi
else
  VERIFY_RC="$RUN_RC"
  echo "WARNING: Remote execution state is unknown" >&2
fi

# Always attempt this check, even when the remote command
# or its result validation failed.
echo "[VERIFY] Checking VM identity after execution"

IDENTITY_RC=0

if AFTER="$(read_vm_identity)"; then
  export AFTER

  if python3 - <<'PY'
import json
import os
import uuid

before = json.loads(os.environ["BEFORE"])
after = json.loads(os.environ["AFTER"])

for field, expected_name in (
    ("vmId", "EXPECTED_VM_ID"),
    ("principalId", "EXPECTED_PRINCIPAL"),
):
    expected = uuid.UUID(os.environ[expected_name])

    actual_before = uuid.UUID(before[field])
    actual_after = uuid.UUID(after[field])

    if actual_before != expected:
        raise SystemExit("ERROR: Initial VM identity mismatch")

    if actual_after != expected:
        raise SystemExit("ERROR: VM identity changed")

print("PASS: VM identity unchanged after Run Command")
PY
  then
    echo "PASS: VM identity rechecked"
  else
    IDENTITY_RC=$?
  fi
else
  IDENTITY_RC=$?
  echo "ERROR: Unable to recheck VM identity" >&2
fi

if [[ "$IDENTITY_RC" -ne 0 ]]; then
  echo "CRITICAL: VM identity could not be confirmed" >&2
  exit 90
fi

if [[ "$VERIFY_RC" -ne 0 ]]; then
  echo "ERROR: Remote operation not confirmed" >&2
  echo "STOP: Automatic retry is prohibited" >&2
  exit 1
fi

echo "PASS: Offline Run Command adapter completed"
