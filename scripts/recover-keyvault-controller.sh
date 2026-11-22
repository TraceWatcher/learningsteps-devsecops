#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:---plan}"

if [[ $# -gt 1 ]] ||
   [[ "$MODE" != "--plan" &&
      "$MODE" != "--prepare-recipient" ]]; then
  echo "Usage: $0 [--plan|--prepare-recipient]" >&2
  exit 2
fi

echo "=== LearningSteps Key Vault Recovery Controller ==="

echo
echo "[1/3] Validating recovery target"

"$ROOT/scripts/prepare-keyvault-transport.sh"

echo
echo "[2/3] Inspecting Key Vault secret"

if "$ROOT/scripts/run-keyvault-inspection.sh"; then
  INSPECTION_RC=0
else
  INSPECTION_RC=$?
fi

case "$INSPECTION_RC" in
  0)
    echo
    echo "RESULT: Existing secret is readable and enabled"
    echo "ACTION: No AGE transport or restore required"
    echo "WARNING: Password consistency still unverified"
    exit 0
    ;;
  3)
    echo
    echo "RESULT: Secret is missing"
    echo "ACTION: Recovery transport may be required"
    ;;
  *)
    echo "ERROR: Secret inspection failed (code $INSPECTION_RC)" >&2
    echo "STOP: Recovery is not authorized" >&2
    exit 1
    ;;
esac

echo
echo "[3/3] Evaluating requested operation"

if [[ "$MODE" == "--plan" ]]; then
  echo "PLAN: Prepare AGE recipient on the new VM"
  echo "PLAN: Transfer only encrypted recovery material"
  echo "PLAN: Verify temporary RBAC authorization"
  echo "PLAN: Require explicit approval before secret write"
  echo "PLAN: Remove temporary RBAC authorization afterwards"
  echo
  echo "PASS: Recovery planning completed"
  echo "INFO: No recipient generated"
  echo "INFO: No secret transferred or modified"
  exit 0
fi

echo "Preparing AGE recipient on recovery VM"

"$ROOT/scripts/prepare-keyvault-recipient.sh" --generate

echo
echo "PASS: Recipient preparation completed"
echo "STOP: Password transport and secret writing not enabled"
