#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$HOME/learningsteps-recovery/temporary-keyvault-rbac.json"
RG="rg-learningsteps-devsecops"
VM="learningsteps-maintenance"
VAULT="kv-lsteps-305c3ba6"
ROLE="Key Vault Secrets Officer"
MODE="${1:-}"

if [[ $# -ne 1 ]] || [[ ! "$MODE" =~ ^(status|grant|cleanup|cleanup-auto)$ ]]; then
  echo "Usage: $0 {status|grant|cleanup|cleanup-auto}" >&2
  exit 2
fi

for tool in az python3; do
  command -v "$tool" >/dev/null || exit 1
done

[[ -f "$STATE" && ! -L "$STATE" ]] || {
  echo "ERROR: RBAC state missing or unsafe" >&2
  exit 1
}

[[ "$(stat -c %a "$STATE")" == "600" ]] || {
  echo "ERROR: RBAC state permissions must be 600" >&2
  exit 1
}

# Validate local state independently of Azure.
eval "$(
python3 - "$STATE" "$RG" "$VAULT" "$ROLE" <<'PY'
import json
import pathlib
import shlex
import sys
import uuid

path, rg, vault, role = sys.argv[1:]
s = json.loads(pathlib.Path(path).read_text())

for field in ("recovery_id", "principal_id", "vm_id"):
    uuid.UUID(s[field])

aid = s["assignment_id"]
name = str(uuid.UUID(aid.rsplit("/", 1)[-1]))

if s["role"] != role or s["status"] not in (
    "prepared", "granted", "removed"
):
    raise SystemExit("ERROR: Unexpected RBAC state")

if not s["vault_id"].lower().endswith(
    f"/resourcegroups/{rg}/providers/microsoft.keyvault/vaults/{vault}".lower()
):
    raise SystemExit("ERROR: Unexpected Key Vault scope")

expected = (
    s["vault_id"].rstrip("/")
    + "/providers/Microsoft.Authorization/roleAssignments/"
    + name
)
if aid.lower() != expected.lower():
    raise SystemExit("ERROR: Invalid assignment ID")

for key, value in {
    "VAULT_ID": s["vault_id"],
    "PRINCIPAL_ID": s["principal_id"],
    "EXPECTED_VM_ID": s["vm_id"],
    "ASSIGNMENT_ID": aid,
    "ASSIGNMENT_NAME": name,
}.items():
    print(f"{key}={shlex.quote(value)}")
PY
)"

SUBSCRIPTION="$(az account show --query id -o tsv)"

[[ "${VAULT_ID,,}" == "/subscriptions/${SUBSCRIPTION,,}/"* ]] || {
  echo "ERROR: Azure subscription mismatch" >&2
  exit 1
}

# Resolve the actual Azure role definition.
ROLE_ID="$(az role definition list \
  --name "$ROLE" \
  --query '[0].id' -o tsv)"

[[ -n "$ROLE_ID" && "$ROLE_ID" != "None" ]] || {
  echo "ERROR: Role definition unavailable" >&2
  exit 1
}

# Fetch role assignments without concealing Azure CLI errors.
ASSIGNMENTS="$(az role assignment list \
  --scope "$VAULT_ID" --all -o json)"

export ASSIGNMENTS ASSIGNMENT_ID PRINCIPAL_ID VAULT_ID ROLE_ID

# Output 0 = absent, 1 = exact match. Other results are errors.
set +e
python3 - <<'PY'
import json
import os

matches = [
    a for a in json.loads(os.environ["ASSIGNMENTS"])
    if a["id"].lower() == os.environ["ASSIGNMENT_ID"].lower()
]

if not matches:
    raise SystemExit(0)

if len(matches) != 1:
    raise SystemExit(20)

a = matches[0]
for actual, expected in (
    (a.get("principalId"), os.environ["PRINCIPAL_ID"]),
    (a.get("scope"), os.environ["VAULT_ID"]),
    (a.get("roleDefinitionId"), os.environ["ROLE_ID"]),
):
    if not actual or actual.lower() != expected.lower():
        raise SystemExit(20)

raise SystemExit(10)
PY
MATCH_RC=$?
set -e

case "$MATCH_RC" in
  0|10) ;;
  *)
    echo "ERROR: RBAC assignment validation failed" >&2
    exit 1
    ;;
esac


if [[ "$MODE" == "status" ]]; then
  LOCAL_STATUS="$(python3 - "$STATE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    state = json.load(f)

print(state["status"])
PY
)"

  echo "Local RBAC state: $LOCAL_STATUS"

  if [[ "$MATCH_RC" -eq 10 ]]; then
    echo "Azure RBAC state: present and matching"

    case "$LOCAL_STATUS" in
      prepared)
        echo "RECONCILE: Azure grant exists but local state is prepared"
        echo "INFO: State can be reconciled after review"
        exit 3
        ;;
      granted)
        echo "PASS: Azure and local RBAC states agree"
        ;;
      removed)
        echo "ERROR: Assignment exists despite removed state" >&2
        exit 1
        ;;
      *)
        echo "ERROR: Invalid local state" >&2
        exit 1
        ;;
    esac
  else
    echo "Azure RBAC state: absent"

    case "$LOCAL_STATUS" in
      prepared)
        echo "PASS: No Azure assignment created yet"
        ;;
      granted)
        echo "RECONCILE: Assignment absent but local state is granted"
        echo "INFO: Verify removal before changing local state"
        exit 3
        ;;
      removed)
        echo "PASS: Azure and local RBAC states agree"
        ;;
      *)
        echo "ERROR: Invalid local state" >&2
        exit 1
        ;;
    esac
  fi

  exit 0
fi


if [[ "$MODE" == "grant" ]]; then
  LOCAL_STATUS="$(python3 - "$STATE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    print(json.load(f)["status"])
PY
)"

  if [[ "$LOCAL_STATUS" == "removed" ]]; then
    echo "ERROR: Completed recovery cannot be granted again" >&2
    exit 1
  fi

  if [[ "$LOCAL_STATUS" == "granted" &&
        "$MATCH_RC" -eq 0 ]]; then
    echo "ERROR: Local state is granted, but Azure assignment is absent" >&2
    echo "STOP: Manual reconciliation required" >&2
    exit 3
  fi

  echo "[SECURITY] Validating new recovery environment"

  "$ROOT/scripts/prepare-keyvault-transport.sh"

  CURRENT_VM_JSON="$(az vm show -g "$RG" -n "$VM" \
    --query '{vmId:vmId,principalId:identity.principalId}' -o json)"
  export CURRENT_VM_JSON EXPECTED_VM_ID

  python3 - <<'PY'
import json
import os

vm = json.loads(os.environ["CURRENT_VM_JSON"])
if (vm.get("vmId") != os.environ["EXPECTED_VM_ID"] or
    vm.get("principalId") != os.environ["PRINCIPAL_ID"]):
    raise SystemExit("ERROR: Recovery VM identity mismatch")
PY

  # A permission problem must not be mistaken for a missing secret.
  if "$ROOT/scripts/run-keyvault-inspection.sh"; then
    echo "STOP: Secret exists; grant is unnecessary"
    exit 1
  else
    INSPECT_RC=$?
  fi

  [[ "$INSPECT_RC" -eq 3 ]] || {
    echo "ERROR: Secret inspection failed" >&2
    exit 1
  }

  if [[ "$MATCH_RC" -eq 10 ]]; then
    echo "INFO: Assignment already exists and matches"
  else
    echo "Creating temporary RBAC assignment"

    az role assignment create \
      --name "$ASSIGNMENT_NAME" \
      --assignee-object-id "$PRINCIPAL_ID" \
      --assignee-principal-type ServicePrincipal \
      --role "$ROLE" \
      --scope "$VAULT_ID" \
      -o none
  fi

  echo "[VERIFY] Reading Azure role assignment"

  VERIFIED_ASSIGNMENT="$(az role assignment list \
    --scope "$VAULT_ID" \
    --all \
    -o json)"

  export VERIFIED_ASSIGNMENT

  python3 - <<'PY'
import json
import os

records = json.loads(os.environ["VERIFIED_ASSIGNMENT"])

matches = [
    item for item in records
    if item.get("id", "").lower()
    == os.environ["ASSIGNMENT_ID"].lower()
]

if len(matches) != 1:
    raise SystemExit(
        "ERROR: Assignment not uniquely confirmed by Azure"
    )

assignment = matches[0]

expected = {
    "principalId": os.environ["PRINCIPAL_ID"],
    "scope": os.environ["VAULT_ID"],
    "roleDefinitionId": os.environ["ROLE_ID"],
}

for field, value in expected.items():
    actual = assignment.get(field)

    if not isinstance(actual, str) or actual.lower() != value.lower():
        raise SystemExit(
            f"ERROR: Assignment verification failed: {field}"
        )

print("PASS: Azure role assignment identity verified")
PY

  echo "[STATE] Recording confirmed grant"

  python3 "$ROOT/scripts/recovery-rbac-state.py" \
    update --status granted

  echo "PASS: Azure grant confirmed and recorded"
  echo "INFO: RBAC propagation may still be pending"
  exit 0
fi



# Cleanup must work even if the recovery VM no longer exists.
if [[ "$MODE" == "cleanup" ||
      "$MODE" == "cleanup-auto" ]]; then

  LOCAL_STATUS="$(python3 - "$STATE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    print(json.load(f)["status"])
PY
)"

  if [[ "$LOCAL_STATUS" == "removed" &&
        "$MATCH_RC" -eq 10 ]]; then
    echo "ERROR: Azure assignment exists despite removed state" >&2
    echo "STOP: Manual reconciliation required" >&2
    exit 3
  fi

  if [[ "$MODE" == "cleanup-auto" ]]; then
    if [[ "$LOCAL_STATUS" != "granted" ||
          "$MATCH_RC" -ne 10 ]]; then
      echo "ERROR: Automatic cleanup requires a confirmed grant" >&2
      exit 3
    fi
  fi

  if [[ "$MATCH_RC" -eq 10 ]]; then
    echo "[CLEANUP] Matching Azure assignment found"
    echo "Assignment: $ASSIGNMENT_ID"

    if [[ "$MODE" == "cleanup" ]]; then
      read -r -p "Type REMOVE to confirm: " CONFIRM

      if [[ "$CONFIRM" != "REMOVE" ]]; then
        echo "ERROR: Cleanup cancelled" >&2
        exit 1
      fi
    else
      echo "AUTO-CLEANUP: Confirmed temporary RBAC grant"
    fi

    az role assignment delete \
      --ids "$ASSIGNMENT_ID"

    echo "INFO: Azure deletion requested"
  else
    echo "INFO: Assignment already absent in Azure"
  fi

  echo "[VERIFY] Checking Azure assignment removal"

  AFTER_CLEANUP="$(az role assignment list \
    --scope "$VAULT_ID" \
    --all \
    -o json)"

  export AFTER_CLEANUP

  python3 - <<'PY'
import json
import os

records = json.loads(os.environ["AFTER_CLEANUP"])
assignment_id = os.environ["ASSIGNMENT_ID"].lower()

matches = [
    item for item in records
    if item.get("id", "").lower() == assignment_id
]

if matches:
    raise SystemExit(
        "ERROR: Temporary RBAC assignment still exists"
    )

print("PASS: Temporary assignment absent in Azure")
PY

  echo "[STATE] Recording confirmed removal"

  python3 "$ROOT/scripts/recovery-rbac-state.py" \
    update --status removed

  echo "PASS: Temporary RBAC cleanup completed"
  exit 0
fi
