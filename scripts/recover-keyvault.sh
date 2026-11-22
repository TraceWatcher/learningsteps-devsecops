#!/usr/bin/env bash
set -euo pipefail

MODE="${1:---dry-run}"

if [[ $# -gt 1 ]] ||
   [[ "$MODE" != "--dry-run" &&
      "$MODE" != "--check-target" &&
      "$MODE" != "--inspect-target" ]]; then
  echo "Usage: $0 [--dry-run|--check-target|--inspect-target]"
  exit 2
fi

RG="rg-learningsteps-devsecops"
VAULT="kv-lsteps-305c3ba6"
PRIVATE_ENDPOINT="pe-learningsteps-keyvault"
PRIVATE_DNS_ZONE="privatelink.vaultcore.azure.net"

BACKUP_DIR="$HOME/learningsteps-recovery"
ORIGINAL="$BACKUP_DIR/original-keyvault.json"
PASSWORD_BACKUP="$BACKUP_DIR/postgres-admin-password.age"
AGE_IDENTITY="$BACKUP_DIR/backup-key.txt"

echo "[1/5] Checking recovery artifacts"

for file in "$ORIGINAL" "$PASSWORD_BACKUP" "$AGE_IDENTITY"; do
  [[ -s "$file" ]] || {
    echo "ERROR: Missing or empty file: $file"
    exit 1
  }
done

for file in "$PASSWORD_BACKUP" "$AGE_IDENTITY"; do
  [[ "$(stat -c '%a' "$file")" == "600" ]] || {
    echo "ERROR: Expected permission 600: $file"
    exit 1
  }
done

echo "[2/5] Checking subscription and original identity"

ORIGINAL_ID="$(python3 - "$ORIGINAL" "$VAULT" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
vault = sys.argv[2]

assert data["name"] == vault
assert data.get("createdAt")
assert data.get("tenantId")
assert data.get("vaultUri", "").startswith("https://")
assert data.get("publicNetworkAccess") == "Disabled"

print(data["id"])
PY
)"

EXPECTED_SUBSCRIPTION="$(
  python3 - "$ORIGINAL_ID" <<'PY'
import sys
parts = sys.argv[1].split("/")
assert len(parts) > 2 and parts[1].lower() == "subscriptions"
print(parts[2])
PY
)"

CURRENT_SUBSCRIPTION="$(az account show --query id -o tsv)"

[[ "$CURRENT_SUBSCRIPTION" == "$EXPECTED_SUBSCRIPTION" ]] || {
  echo "ERROR: Wrong Azure subscription"
  exit 1
}

echo "PASS: Azure subscription matches original reference"

echo "[3/5] Checking Key Vault"

CURRENT_JSON="$(az keyvault show \
  --resource-group "$RG" \
  --name "$VAULT" \
  -o json)"

export CURRENT_JSON ORIGINAL_ID ORIGINAL

python3 - <<'PY'
import json
import os
from pathlib import Path

original = json.loads(Path(os.environ["ORIGINAL"]).read_text())
current = json.loads(os.environ["CURRENT_JSON"])

assert current["id"].lower() == os.environ["ORIGINAL_ID"].lower()
assert current["properties"]["publicNetworkAccess"] == "Disabled"
assert current["properties"]["enableRbacAuthorization"] is True

created = (current.get("systemData") or {}).get("createdAt")
original_created = original["createdAt"]

print("PASS: Key Vault identity and network configuration")

if created == original_created:
    print("INFO: Original creation timestamp matches")
    print("INFO: Could be original or recovered vault")
elif created:
    print("INFO: Creation timestamp differs from original")
else:
    print("INFO: Current creation timestamp unavailable")

print("INFO: No conclusion about secret contents")
PY

echo "[4/5] Checking Private Endpoint"

PE_STATUS="$(az network private-endpoint show \
  --resource-group "$RG" \
  --name "$PRIVATE_ENDPOINT" \
  --query 'privateLinkServiceConnections[].privateLinkServiceConnectionState.status' \
  -o tsv)"

[[ "$PE_STATUS" == "Approved" ]] || {
  echo "ERROR: Private Endpoint is not approved"
  exit 1
}

echo "PASS: Private Endpoint approved"

echo "[5/5] Checking private DNS record"

PRIVATE_IP="$(az network private-dns record-set a show \
  --resource-group "$RG" \
  --zone-name "$PRIVATE_DNS_ZONE" \
  --name "$VAULT" \
  --query 'aRecords[0].ipv4Address' \
  -o tsv)"

python3 - "$PRIVATE_IP" <<'PY'
import ipaddress
import sys

ip = ipaddress.ip_address(sys.argv[1])
assert isinstance(ip, ipaddress.IPv4Address)
assert ip.is_private
print(f"PASS: Private DNS points to {ip}")
PY

# ----------------------------------------------------
# Read-only Key Vault recovery target inspection
# ----------------------------------------------------

if [[ "$MODE" == "--inspect-target" ]]; then

  echo "[INSPECT] Inspecting Key Vault recovery target"

  export CURRENT_JSON ORIGINAL

  python3 - <<'PY'
import json
import os
from datetime import datetime
from pathlib import Path

original = json.loads(
    Path(os.environ["ORIGINAL"]).read_text()
)

current = json.loads(os.environ["CURRENT_JSON"])

def parse_timestamp(value):
    if not value:
        raise SystemExit(
            "ERROR: Missing creation timestamp"
        )
    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

original_created = parse_timestamp(
    original["createdAt"]
)

current_created = parse_timestamp(
    (current.get("systemData") or {}).get("createdAt")
)

same_generation = original_created == current_created

properties = current["properties"]

print("Vault:", current["name"])
print("Creation timestamp matches original:", same_generation)
print("Public access:", properties.get("publicNetworkAccess"))
print("RBAC enabled:", properties.get("enableRbacAuthorization"))

if same_generation:
    print(
        "INFO: Vault may be original or recovered from soft delete"
    )
else:
    print(
        "INFO: Vault creation timestamp differs from original"
    )

print("INFO: Secret existence has not been verified")
print("INFO: No authorization to modify secrets")
PY

  echo
  echo "PASS: Read-only target inspection completed"
fi

if [[ "$MODE" == "--check-target" ]]; then
  echo "[SECURITY] Checking recovery target"

  export CURRENT_JSON ORIGINAL

  python3 - <<'PY'
import json
import os
from datetime import datetime
from pathlib import Path

original = json.loads(
    Path(os.environ["ORIGINAL"]).read_text()
)
current = json.loads(os.environ["CURRENT_JSON"])

def parse_timestamp(value):
    if not value:
        raise SystemExit("ERROR: Missing creation timestamp")
    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

original_created = parse_timestamp(original["createdAt"])
current_created = parse_timestamp(
    (current.get("systemData") or {}).get("createdAt")
)

if original_created == current_created:
    raise SystemExit(
        "ERROR: Original or recovered Key Vault detected.\n"
        "Target is not approved for secret restoration."
    )

print("PASS: Key Vault creation timestamp differs")
print("INFO: This is not yet authorization to restore secrets")
PY

  echo "PASS: Preliminary target check completed"
fi

echo
echo "PASS: Key Vault recovery prerequisites checked"
echo "DRY RUN: No secret values were accessed."
echo "DRY RUN: No Azure or Kubernetes resources modified."
