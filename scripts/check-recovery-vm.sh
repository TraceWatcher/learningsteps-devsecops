#!/usr/bin/env bash
set -euo pipefail

RG="rg-learningsteps-devsecops"
VM="learningsteps-maintenance"

ORIGINAL="$HOME/learningsteps-recovery/original-maintenance-vm.json"

[[ $# -eq 0 ]] || {
  echo "Usage: $0"
  exit 2
}

[[ -s "$ORIGINAL" ]] || {
  echo "ERROR: Original VM reference missing"
  exit 1
}

echo "[1/3] Checking Azure subscription"

EXPECTED_SUBSCRIPTION="$(python3 - "$ORIGINAL" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
parts = data["id"].split("/")

assert parts[1].lower() == "subscriptions"
print(parts[2])
PY
)"

CURRENT_SUBSCRIPTION="$(az account show --query id -o tsv)"

[[ "$CURRENT_SUBSCRIPTION" == "$EXPECTED_SUBSCRIPTION" ]] || {
  echo "ERROR: Wrong Azure subscription"
  exit 1
}

echo "[2/3] Reading current Maintenance VM"

CURRENT_JSON="$(az vm show \
  --resource-group "$RG" \
  --name "$VM" \
  --query '{
    id:id,
    vmId:vmId,
    principalId:identity.principalId,
    identityType:identity.type
  }' \
  -o json)"

export CURRENT_JSON ORIGINAL

echo "[3/3] Checking VM generation and identity"

python3 - <<'PY'
import json
import os
from pathlib import Path

original = json.loads(
    Path(os.environ["ORIGINAL"]).read_text()
)
current = json.loads(os.environ["CURRENT_JSON"])

if current["id"].lower() != original["id"].lower():
    raise SystemExit("ERROR: Unexpected VM resource ID")

if current.get("identityType") != "SystemAssigned":
    raise SystemExit("ERROR: Expected system-assigned identity")

old_vm_id = original.get("vmId")
new_vm_id = current.get("vmId")

old_principal = original.get("principalId")
new_principal = current.get("principalId")

if not all((old_vm_id, new_vm_id, old_principal, new_principal)):
    raise SystemExit("ERROR: Missing VM identity information")

if new_vm_id.lower() == old_vm_id.lower():
    raise SystemExit(
        "ERROR: Original Maintenance VM detected"
    )

if new_principal.lower() == old_principal.lower():
    raise SystemExit(
        "ERROR: Original Managed Identity detected"
    )

print("PASS: New Maintenance VM generation verified")
print("PASS: New Managed Identity verified")
print("INFO: This does not authorize a Secret Restore")
PY
