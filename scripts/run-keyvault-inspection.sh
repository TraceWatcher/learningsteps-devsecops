#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RG="rg-learningsteps-devsecops"
VM="learningsteps-maintenance"
VAULT="kv-lsteps-305c3ba6"

echo "[1/4] Running Key Vault preflight"

"$ROOT/scripts/recover-keyvault.sh" --inspect-target

echo "[2/4] Checking maintenance VM status"

if ! az vm get-instance-view \
  --resource-group "$RG" \
  --name "$VM" \
  --query 'instanceView.statuses[].code' \
  -o tsv | grep -Fxq "PowerState/running"; then

  echo "ERROR: Maintenance VM is not running"
  echo "Start the VM explicitly before inspection."
  exit 1
fi

echo "[3/4] Reading private endpoint IP"

PRIVATE_IP="$(az network private-dns record-set a show \
  --resource-group "$RG" \
  --zone-name privatelink.vaultcore.azure.net \
  --name "$VAULT" \
  --query 'aRecords[0].ipv4Address' \
  -o tsv)"

python3 - "$PRIVATE_IP" <<'PY'
import ipaddress
import sys

ip = ipaddress.ip_address(sys.argv[1])
if not isinstance(ip, ipaddress.IPv4Address) or not ip.is_private:
    raise SystemExit("ERROR: Invalid private endpoint IP")
PY

echo "[4/4] Executing remote secret inspection"

SCRIPT_B64="$(base64 -w 0 \
  "$ROOT/scripts/inspect-keyvault-secret.py")"

REMOTE_SCRIPT="$(cat <<SCRIPT
set +e
printf '%s' '$SCRIPT_B64' | base64 -d | python3 - \
  --vault '$VAULT' \
  --private-ip '$PRIVATE_IP'
rc=\$?
printf '__LS_KV_INSPECT_RC__=%s\n' "\$rc"
exit 0
SCRIPT
)"

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
import re

result = json.loads(os.environ["RESULT"])

entries = result.get("value", [])
if not entries:
    raise SystemExit("ERROR: No Run Command result")

entry = entries[0]

if entry.get("code") != "ProvisioningState/succeeded":
    raise SystemExit("ERROR: Azure Run Command failed")

message = entry.get("message", "")

matches = re.findall(
    r"(?m)^__LS_KV_INSPECT_RC__=(\d+)\s*$",
    message
)

if len(matches) != 1:
    raise SystemExit(
        "ERROR: Missing or ambiguous remote exit status"
    )

code = int(matches[0])

if code == 0:
    print("PASS: Secret exists, enabled and readable")
elif code == 3:
    raise SystemExit(
        "MISSING: Secret not found. Restore requires review."
    )
else:
    raise SystemExit(
        f"ERROR: Remote secret inspection failed (code {code})"
    )
PY
