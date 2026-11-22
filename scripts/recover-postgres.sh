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
PG_IDENTITY_FILE="$RECOVERY_DIR/original-postgres.json"

MODE="${1:---dry-run}"

if [[ $# -gt 1 ]] ||
   [[ "$MODE" != "--dry-run" &&
      "$MODE" != "--restore" &&
      "$MODE" != "--check-target" &&
      "$MODE" != "--verify" ]]; then
  echo "Usage: $0 [--dry-run|--check-target|--restore|--verify]"
  exit 2
fi

for tool in az kubectl age pg_restore python3; do
  command -v "$tool" >/dev/null || {
    echo "ERROR: Missing dependency: $tool"
    exit 1
  }
done

echo "[1/6] Checking recovery files"

for file in \
  "$BACKUP_FILE" \
  "$KEY_FILE" \
  "$UID_FILE" \
  "$PG_IDENTITY_FILE"; do

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
  if [[ "$MODE" == "--restore" || "$MODE" == "--verify" ]]; then
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

echo "[SECURITY] Checking PostgreSQL generation"

CURRENT_PG_CREATED_AT="$(az postgres flexible-server show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$POSTGRES_NAME" \
  --query systemData.createdAt \
  -o tsv)"

ORIGINAL_PG_CREATED_AT="$(python3 - "$PG_IDENTITY_FILE" <<'PY'
import json
import sys

with open(sys.argv[1]) as f:
    data = json.load(f)

print(data["createdAt"])
PY
)"

if [[ -z "$CURRENT_PG_CREATED_AT" ||
      "$CURRENT_PG_CREATED_AT" == "None" ||
      -z "$ORIGINAL_PG_CREATED_AT" ]]; then
  echo "ERROR: PostgreSQL creation timestamp unavailable"
  exit 1
fi

if [[ "$CURRENT_PG_CREATED_AT" == "$ORIGINAL_PG_CREATED_AT" ]]; then
  if [[ "$MODE" == "--restore" ]]; then
    echo "ERROR: Original PostgreSQL instance detected."
    echo "Restore is prohibited on the original database server."
    exit 1
  fi

  echo "INFO: Original PostgreSQL instance detected"
else
  echo "PASS: PostgreSQL creation timestamp differs from original"
fi

echo "[6/6] Checking encrypted backup"

age -d \
  -i "$KEY_FILE" \
  "$BACKUP_FILE" |
pg_restore --list > /dev/null

echo "PASS: Encrypted PostgreSQL archive is readable"

echo
echo "PASS: PostgreSQL recovery preflight completed"

if [[ "$MODE" == "--dry-run" ]]; then
  echo "MODE: DRY RUN"
  echo "No Azure, Kubernetes or PostgreSQL resources were modified."
else
  echo "MODE: $MODE"
  echo "Preflight completed. Database has not been modified."
fi

if [[ "$MODE" == "--check-target" ||
      "$MODE" == "--restore" ||
      "$MODE" == "--verify" ]]; then
  echo
  echo "[TARGET CHECK] Preparing PostgreSQL client"

TEMP_DIR="$(mktemp -d)"
CLIENT_POD="learningsteps-db-recovery-$(date +%s)-$$"
POD_CREATED=false

cleanup() {
  local status=$?
  trap - EXIT

  if [[ "$POD_CREATED" == true ]]; then
    kubectl delete pod "$CLIENT_POD" \
      -n learningsteps \
      --ignore-not-found \
      --wait=true || echo "WARNING: Manual pod cleanup required: $CLIENT_POD"
  fi

  rm -rf -- "$TEMP_DIR"
  exit "$status"
}

trap cleanup EXIT

"$ROOT/scripts/prepare-db-recovery-client.sh" \
  "$TEMP_DIR/db-recovery-client.yaml"

# Assign a unique pod name without changing the source manifest.
export CLIENT_POD
export MANIFEST="$TEMP_DIR/db-recovery-client.yaml"

python3 - <<'PY'
import os
import re
from pathlib import Path

path = Path(os.environ["MANIFEST"])
content = path.read_text()

updated, count = re.subn(
    r'^  name: learningsteps-db-recovery-client$',
    f'  name: {os.environ["CLIENT_POD"]}',
    content,
    flags=re.MULTILINE,
)

if count != 1:
    raise SystemExit("ERROR: Expected exactly one pod name")

path.write_text(updated)
PY

echo "[TARGET CHECK] Starting PostgreSQL client"

# create refuses to take over an existing resource.
kubectl create -f "$MANIFEST"
POD_CREATED=true

  kubectl wait \
    -n learningsteps \
    --for=condition=Ready \
    "pod/$CLIENT_POD" \
    --timeout=120s

  if [[ "$MODE" == "--verify" ]]; then
    echo "[VERIFY] Checking restored PostgreSQL data"

    {
      printf '%s\n' \
        'set -eu' \
        'export PGPASSWORD="$(cat /mnt/secrets/postgres-admin-password)"' \
        'export PGOPTIONS="-c default_transaction_read_only=on"' \
        'psql -X -v ON_ERROR_STOP=1 <<'\''SQL'\'''

      cat "$ROOT/scripts/sql/verify-restored-database.sql"

      printf '%s\n' 'SQL'
    } | kubectl exec -i \
        -n learningsteps \
        "$CLIENT_POD" \
        -- sh -s

    echo
    echo "PASS: PostgreSQL recovery verification completed"
    echo "No database modifications were performed."
    exit 0
  fi

  echo "[TARGET CHECK] Checking database schema"

  {
    printf '%s\n' \
      'set -eu' \
      'export PGPASSWORD="$(cat /mnt/secrets/postgres-admin-password)"' \
      'export PGOPTIONS="-c default_transaction_read_only=on"' \
      'psql -X -v ON_ERROR_STOP=1 <<'\''SQL'\'''

    cat "$ROOT/scripts/sql/check-empty-database.sql"

    printf '%s\n' 'SQL'
  } | kubectl exec -i \
      -n learningsteps \
      "$CLIENT_POD" \
      -- sh -s

echo "PASS: Database target contains no conflicting schema objects"

if [[ "$MODE" == "--check-target" ]]; then
  exit 0
fi

# ----------------------------------------------------
# Restore safety checks
# ----------------------------------------------------

echo "[RESTORE] Checking for competing Kubernetes workloads"

export CLIENT_POD

kubectl get deployments,jobs,cronjobs,pods \
  -n learningsteps \
  -o json |
python3 -c '
import json
import sys

objects = json.load(sys.stdin)["items"]
blocking = []

for obj in objects:
    kind = obj["kind"]
    name = obj["metadata"]["name"]

    # API deployments must not be running during recovery.
    if kind == "Deployment" and name == "learningsteps-api":
        replicas = obj.get("spec", {}).get("replicas", 1)
        if replicas > 0:
            blocking.append(f"{kind}/{name}: replicas={replicas}")

    # Reject active application API pods, including terminating ones.
    if kind == "Pod" and obj.get("metadata", {}).get(
        "labels", {}
    ).get("app") == "learningsteps-api":
        phase = obj.get("status", {}).get("phase")
        if phase not in ("Succeeded", "Failed"):
            blocking.append(f"{kind}/{name}: {phase}")

    # A running database initialization job must block restore.
    if kind == "Job" and name.startswith("learningsteps-db-init"):
        status = obj.get("status", {})
        if (
            status.get("active", 0) > 0
            or status.get("succeeded", 0) == 0
            and status.get("failed", 0) == 0
        ):
            blocking.append(f"{kind}/{name}: incomplete")

    # Prevent future scheduled database initialization.
    if kind == "CronJob" and name.startswith("learningsteps-db-init"):
        if not obj.get("spec", {}).get("suspend", False):
            blocking.append(f"{kind}/{name}: not suspended")

if blocking:
    print("ERROR: Potential database writers detected:")
    for item in blocking:
        print(" -", item)
    sys.exit(1)

print("PASS: No known competing application writers detected")
'

echo "[RESTORE] Checking active PostgreSQL connections"

kubectl exec \
  -n learningsteps \
  "$CLIENT_POD" \
  -- sh -ec '
    export PGPASSWORD="$(cat /mnt/secrets/postgres-admin-password)"
    export PGOPTIONS="-c default_transaction_read_only=on"

    ACTIVE=$(psql -X -A -t -v ON_ERROR_STOP=1 \
      -c "
        SELECT COUNT(*)
        FROM pg_stat_activity
        WHERE datname = current_database()
          AND pid <> pg_backend_pid()
          AND backend_type = '\''client backend'\'';
      ")

    if [ "$ACTIVE" != "0" ]; then
      echo "ERROR: Other PostgreSQL connections detected: $ACTIVE"
      exit 1
    fi

    echo "PASS: No competing PostgreSQL connections detected"
  '

echo
echo "DATABASE RESTORE REQUEST"
echo "Resource Group: $RESOURCE_GROUP"
echo "PostgreSQL:     $POSTGRES_NAME"
echo "Database:       learning_journal"
echo "Backup:         $(basename "$BACKUP_FILE")"
echo
echo "This will restore the database schema and data."
echo

if [[ ! -t 0 ]]; then
  echo "ERROR: Interactive confirmation required"
  exit 1
fi

read -r -p \
  "Type 'RESTORE learning_journal' to continue: " \
  CONFIRMATION

if [[ "$CONFIRMATION" != "RESTORE learning_journal" ]]; then
  echo "Restore cancelled"
  exit 1
fi

echo "[RESTORE] Rechecking database emptiness"

{
  printf '%s\n' \
    'set -eu' \
    'export PGPASSWORD="$(cat /mnt/secrets/postgres-admin-password)"' \
    'export PGOPTIONS="-c default_transaction_read_only=on"' \
    'psql -X -v ON_ERROR_STOP=1 <<'\''SQL'\'''

  cat "$ROOT/scripts/sql/check-empty-database.sql"

  printf '%s\n' 'SQL'
} | kubectl exec -i \
    -n learningsteps \
    "$CLIENT_POD" \
    -- sh -s

echo "[RESTORE] Restoring encrypted PostgreSQL backup"

age -d \
  -i "$KEY_FILE" \
  "$BACKUP_FILE" |
kubectl exec -i \
  -n learningsteps \
  "$CLIENT_POD" \
  -- sh -ec '
    export PGPASSWORD="$(cat /mnt/secrets/postgres-admin-password)"

    pg_restore \
      --host="$PGHOST" \
      --port="$PGPORT" \
      --username="$PGUSER" \
      --dbname="$PGDATABASE" \
      --no-owner \
      --no-acl \
      --single-transaction \
      --exit-on-error \
      --verbose
  '

echo "[RESTORE] Verifying restored data"

{
  printf '%s\n' \
    'set -eu' \
    'export PGPASSWORD="$(cat /mnt/secrets/postgres-admin-password)"' \
    'export PGOPTIONS="-c default_transaction_read_only=on"' \
    'psql -X -v ON_ERROR_STOP=1 <<'\''SQL'\'''

  cat "$ROOT/scripts/sql/verify-restored-database.sql"

  printf '%s\n' 'SQL'
} | kubectl exec -i \
    -n learningsteps \
    "$CLIENT_POD" \
    -- sh -s

echo "PASS: PostgreSQL restore and basic integrity checks completed"
exit 0
fi
