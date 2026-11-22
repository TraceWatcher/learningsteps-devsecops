#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RG="rg-learningsteps-devsecops"
VM="learningsteps-maintenance"

MODE="${1:---check}"

[[ $# -le 1 &&
   ( "$MODE" == "--check" ||
     "$MODE" == "--generate" ) ]] || {
  echo "Usage: $0 [--check|--generate]"
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

if [[ "$MODE" == "--generate" ]]; then
  echo "[GENERATE] Preparing AGE recipient"

  BEFORE_JSON="$(az vm show \
    --resource-group "$RG" \
    --name "$VM" \
    --query '{
      vmId:vmId,
      principalId:identity.principalId
    }' \
    -o json)"

  SCRIPT_B64="$(base64 -w 0 \
    "$ROOT/scripts/generate-keyvault-recipient.py")"

  REMOTE_SCRIPT="$(cat <<SCRIPT
set +e

printf '%s' '$SCRIPT_B64' | base64 -d | python3 -
rc=\$?

printf '__LS_RECIPIENT_RC__=%s\n' "\$rc"
exit 0
SCRIPT
)"

  RESULT="$(az vm run-command invoke \
    --resource-group "$RG" \
    --name "$VM" \
    --command-id RunShellScript \
    --scripts "$REMOTE_SCRIPT" \
    -o json)"

  AFTER_JSON="$(az vm show \
    --resource-group "$RG" \
    --name "$VM" \
    --query '{
      vmId:vmId,
      principalId:identity.principalId
    }' \
    -o json)"

  export BEFORE_JSON AFTER_JSON RESULT

  python3 - <<'PY'
import json
import os
import re

before = json.loads(os.environ["BEFORE_JSON"])
after = json.loads(os.environ["AFTER_JSON"])
result = json.loads(os.environ["RESULT"])

required = ("vmId", "principalId")

for field in required:
    if not before.get(field) or not after.get(field):
        raise SystemExit(
            f"ERROR: Missing VM identity field: {field}"
        )

if before != after:
    raise SystemExit(
        "ERROR: Maintenance VM identity changed"
    )

entries = result.get("value", [])

if len(entries) != 1:
    raise SystemExit(
        "ERROR: Unexpected Run Command result"
    )

entry = entries[0]

if entry.get("code") != "ProvisioningState/succeeded":
    raise SystemExit("ERROR: Azure Run Command failed")

message = entry.get("message", "")

exit_codes = re.findall(
    r"(?m)^__LS_RECIPIENT_RC__=(\d+)\s*$",
    message
)

recipients = re.findall(
    r"(?m)^RECIPIENT=(age1[0-9a-z]+)\s*$",
    message
)

if len(exit_codes) != 1 or exit_codes[0] != "0":
    raise SystemExit(
        "ERROR: Remote key generation failed"
    )

if len(recipients) != 1:
    raise SystemExit(
        "ERROR: Missing or ambiguous AGE recipient"
    )

print("PASS: VM identity unchanged")
print("PASS: AGE recipient generated on recovery VM")
print("RECIPIENT=" + recipients[0])
PY
fi

echo
echo "PASS: Recipient preparation prerequisites verified"
echo "INFO: No cryptographic keys generated"
echo "INFO: No secrets transferred or modified"
