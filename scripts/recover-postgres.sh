#!/usr/bin/env bash
set -euo pipefail

# LearningSteps PostgreSQL Recovery
# Initial version: read-only preflight checks.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RECOVERY_DIR="$HOME/learningsteps-recovery"

EXPECTED_SUBSCRIPTION="901cb597-1248-4bc6-8b92-0452114c48b9"
RESOURCE_GROUP="rg-learningsteps-devsecops"
AKS_NAME="aks-learningsteps"
POSTGRES_NAME="psql-learningsteps-305c3ba6"

BACKUP_FILE="$RECOVERY_DIR/learningsteps-20261121-180103.dump.age"
KEY_FILE="$RECOVERY_DIR/backup-key.txt"
UID_FILE="$RECOVERY_DIR/original-cluster-uid.txt"

MODE="${1:---dry-run}"

if [[ $# -gt 1 ]] ||
   [[ "$MODE" != "--dry-run" && "$MODE" != "--restore" ]]; then
  echo "Usage: $0 [--dry-run|--restore]"
  exit 2
fi

for tool in az kubectl age pg_restore python3; do
  command -v "$tool" >/dev/null || {
    echo "ERROR: Missing dependency: $tool"
    exit 1
  }
done

echo "[1/6] Checking recovery files"

for file in "$BACKUP_FILE" "$KEY_FILE" "$UID_FILE"; do
  [[ -s "$file" ]] || {
    echo "ERROR: Missing or empty recovery file: $file"
    exit 1
  }
done

echo "PASS: Recovery files available"

echo "[2/6] Checking Azure subscription"

SUBSCRIPTION="$(az account show --query id -o tsv)"

[[ "$SUBSCRIPTION" == "$EXPECTED_SUBSCRIPTION" ]] || {
  echo "ERROR: Unexpected Azure subscription"
  exit 1
}

echo "PASS: Correct Azure subscription"

echo "[3/6] Checking AKS identity"

AKS_FQDN="$(az aks show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$AKS_NAME" \
  --query fqdn -o tsv)"

AKS_ID="$(az aks show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$AKS_NAME" \
  --query id -o tsv)"

KUBE_SERVER="$(kubectl config view --minify \
  -o jsonpath='{.clusters[0].cluster.server}')"

export AKS_FQDN AKS_ID KUBE_SERVER EXPECTED_SUBSCRIPTION

python3 - <<'PY'
import os
from urllib.parse import urlparse

expected = (
    f"/subscriptions/{os.environ['EXPECTED_SUBSCRIPTION']}"
    "/resourceGroups/rg-learningsteps-devsecops"
    "/providers/Microsoft.ContainerService/managedClusters/aks-learningsteps"
)

assert os.environ["AKS_ID"].lower() == expected.lower()

server = urlparse(os.environ["KUBE_SERVER"])
assert server.scheme == "https"
assert server.hostname == os.environ["AKS_FQDN"]
assert server.port in (None, 443)

print("PASS: AKS resource and API endpoint match")
PY

echo "[4/6] Checking cluster generation"

ORIGINAL_UID="$(cat "$UID_FILE")"

CURRENT_UID="$(kubectl get namespace kube-system \
  -o jsonpath='{.metadata.uid}')"

[[ -n "$CURRENT_UID" ]] || {
  echo "ERROR: Unable to read cluster UID"
  exit 1
}

if [[ "$CURRENT_UID" == "$ORIGINAL_UID" ]]; then
  if [[ "$MODE" == "--restore" ]]; then
    echo "ERROR: Original AKS cluster detected."
    echo "Database restore is prohibited on the original cluster."
    exit 1
  fi

  echo "INFO: Original AKS cluster detected"
  echo "INFO: Restore remains blocked"
else
  echo "INFO: Cluster UID differs from original"
fi

echo "[5/6] Checking PostgreSQL server"

PG_INFO="$(az postgres flexible-server show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$POSTGRES_NAME" \
  --query '{name:name,state:state,version:version}' \
  -o json)"

export PG_INFO

python3 - <<'PY'
import json
import os

db = json.loads(os.environ["PG_INFO"])

assert db["version"] == "16", "Unexpected PostgreSQL version"
assert db["state"] == "Ready", "PostgreSQL is not ready"

print("PASS: Azure PostgreSQL 16 is ready")
PY

echo "[6/6] Checking encrypted backup"

age -d \
  -i "$KEY_FILE" \
  "$BACKUP_FILE" |
pg_restore --list > /dev/null

echo "PASS: Encrypted PostgreSQL archive is readable"

echo
echo "PASS: PostgreSQL recovery preflight completed"
echo "MODE: DRY RUN"
echo "No Azure, Kubernetes or PostgreSQL resources were modified."

if [[ "$MODE" == "--restore" ]]; then
  echo "ERROR: Restore implementation is not enabled yet."
  exit 1
fi