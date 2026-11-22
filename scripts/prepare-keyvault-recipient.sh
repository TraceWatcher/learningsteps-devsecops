#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RG="rg-learningsteps-devsecops"
VM="learningsteps-maintenance"

MODE="${1:---check}"

[[ $# -le 1 && "$MODE" == "--check" ]] || {
  echo "Usage: $0 [--check]"
  exit 2
}

echo "[1/3] Checking recovery environment"

"$ROOT/scripts/prepare-keyvault-transport.sh"

echo "[2/3] Checking VM identity"

VM_JSON="$(az vm show \
  --resource-group "$RG" \
  --name "$VM" \
  --query '{
    vmId:vmId,
    principalId:identity.principalId,
    identityType:identity.type
  }' \
  -o json)"

export VM_JSON

python3 - <<'PY'
import json
import os

vm = json.loads(os.environ["VM_JSON"])

if vm.get("identityType") != "SystemAssigned":
    raise SystemExit("ERROR: Invalid VM identity type")

if not vm.get("vmId") or not vm.get("principalId"):
    raise SystemExit("ERROR: Missing VM identity")

print("PASS: Maintenance VM identity available")
PY

echo "[3/3] Checking AGE availability on recovery VM"

REMOTE_SCRIPT='
set -eu

if ! command -v age >/dev/null 2>&1; then
  echo "ERROR: age is not installed"
  exit 1
fi

if ! command -v age-keygen >/dev/null 2>&1; then
  echo "ERROR: age-keygen is not installed"
  exit 1
fi

echo "PASS: AGE tools available"
'

RESULT="$(az vm run-command invoke \
  --resource-group "$RG" \
  --name "$VM" \
  --command-id RunShellScript \
  --scripts "$REMOTE_SCRIPT" \
  -o json)"

export RESULT

python3 - <<'PY'
import json
import os

result = json.loads(os.environ["RESULT"])
entries = result.get("value", [])

if len(entries) != 1:
    raise SystemExit("ERROR: Unexpected Run Command result")

entry = entries[0]

if entry.get("code") != "ProvisioningState/succeeded":
    raise SystemExit("ERROR: Run Command failed")

message = entry.get("message", "")

if "[stderr]" not in message or "[stdout]" not in message:
    raise SystemExit("ERROR: Unexpected Run Command output")

stdout = message.split("[stdout]", 1)[1].split("[stderr]", 1)[0]

if "PASS: AGE tools available" not in stdout:
    raise SystemExit("ERROR: AGE prerequisites not verified")

print("PASS: Recovery VM has required AGE tools")
PY

echo
echo "PASS: Recipient preparation prerequisites verified"
echo "INFO: No cryptographic keys generated"
echo "INFO: No secrets transferred or modified"
