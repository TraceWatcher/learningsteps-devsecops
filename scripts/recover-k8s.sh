#!/usr/bin/env bash
set -euo pipefail

# LearningSteps Kubernetes Recovery
# Phase 1: Prepare and validate manifests only.
# No cluster resources are modified.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT/infra-terraform"

EXPECTED_SUBSCRIPTION="901cb597-1248-4bc6-8b92-0452114c48b9"
RESOURCE_GROUP="rg-learningsteps-devsecops"
AKS_NAME="aks-learningsteps"
NAMESPACE="learningsteps"

MODE="${1:---dry-run}"

if [[ $# -gt 1 ]] ||
   [[ "$MODE" != "--dry-run" &&
      "$MODE" != "--bootstrap" &&
      "$MODE" != "--deploy" ]]; then
  echo "Usage: $0 [--dry-run|--bootstrap|--deploy]"
  exit 2
fi

for tool in az kubectl terraform python3 kubeconform; do
  command -v "$tool" >/dev/null || {
    echo "ERROR: Missing dependency: $tool"
    exit 1
  }
done

echo "[1/6] Checking Azure subscription"

ACTUAL_SUBSCRIPTION="$(az account show --query id -o tsv)"

if [[ "$ACTUAL_SUBSCRIPTION" != "$EXPECTED_SUBSCRIPTION" ]]; then
  echo "ERROR: Unexpected Azure subscription"
  exit 1
fi

echo "[2/6] Verifying AKS target"

AKS_JSON="$(az aks show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$AKS_NAME" \
  -o json)"

KUBE_JSON="$(kubectl config view --minify -o json)"

export AKS_JSON KUBE_JSON EXPECTED_SUBSCRIPTION

python3 - <<'PY'
import json
import os
from urllib.parse import urlparse

aks = json.loads(os.environ["AKS_JSON"])
kube = json.loads(os.environ["KUBE_JSON"])

expected_id = (
    f"/subscriptions/{os.environ['EXPECTED_SUBSCRIPTION']}"
    "/resourceGroups/rg-learningsteps-devsecops"
    "/providers/Microsoft.ContainerService/managedClusters/aks-learningsteps"
)

assert aks["id"].lower() == expected_id.lower(), "Wrong AKS resource"
assert aks["provisioningState"] == "Succeeded", "AKS not ready"

server = kube["clusters"][0]["cluster"]["server"]
url = urlparse(server)

assert url.scheme == "https", "Kubernetes API is not HTTPS"
assert url.hostname == aks["fqdn"], "Kubernetes API FQDN mismatch"
assert url.port in (None, 443), "Unexpected Kubernetes API port"

print("PASS: Azure subscription and AKS API target match")
PY

echo "[3/6] Reading Terraform outputs"

API_CLIENT_ID="$(terraform -chdir="$TF_DIR" \
  output -raw learningsteps_api_client_id)"

KEYVAULT_TENANT_ID="$(terraform -chdir="$TF_DIR" \
  output -raw keyvault_tenant_id)"

mapfile -t KEYVAULT_NAMES < <(
  az keyvault list \
    --resource-group "$RESOURCE_GROUP" \
    --query '[].name' \
    -o tsv
)

if [[ "${#KEYVAULT_NAMES[@]}" -ne 1 ]]; then
  echo "ERROR: Expected exactly one Key Vault"
  exit 1
fi

KEYVAULT_NAME="${KEYVAULT_NAMES[0]}"

[[ -n "$KEYVAULT_TENANT_ID" &&
   "$KEYVAULT_TENANT_ID" != "None" ]] || {
  echo "ERROR: Key Vault tenant ID missing"
  exit 1
}

echo "[4/6] Reading ACR and AKS default domain"

mapfile -t ACR_SERVERS < <(
  az acr list \
    --resource-group "$RESOURCE_GROUP" \
    --query '[].loginServer' \
    -o tsv
)

if [[ "${#ACR_SERVERS[@]}" -ne 1 ]]; then
  echo "ERROR: Expected exactly one ACR in resource group"
  exit 1
fi

ACR_LOGIN_SERVER="${ACR_SERVERS[0]}"

[[ "$ACR_LOGIN_SERVER" == *.azurecr.io ]] || {
  echo "ERROR: Invalid ACR login server"
  exit 1
}

DOMAIN="$(az aks approuting defaultdomain show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$AKS_NAME" \
  --query domainName -o tsv)"

[[ -n "$DOMAIN" && "$DOMAIN" != "None" ]] || {
  echo "ERROR: AKS default domain missing"
  exit 1
}

export API_CLIENT_ID ACR_LOGIN_SERVER DOMAIN
export KEYVAULT_NAME KEYVAULT_TENANT_ID

echo "[5/6] Preparing recovery manifests"

OUT_DIR="$(mktemp -d /tmp/learningsteps-recovery.XXXXXX)"
chmod 700 "$OUT_DIR"

export ROOT OUT_DIR

python3 - <<'PY'
from pathlib import Path
import os
import shutil

root = Path(os.environ["ROOT"]) / "k8s-manifests"
out = Path(os.environ["OUT_DIR"])

client_id = os.environ["API_CLIENT_ID"]
registry = os.environ["ACR_LOGIN_SERVER"]
hostname = f"learningsteps.{os.environ['DOMAIN']}"
keyvault_name = os.environ["KEYVAULT_NAME"]
tenant_id = os.environ["KEYVAULT_TENANT_ID"]

files = [
    "namespace.yaml",
    "serviceaccount.yaml",
    "secretproviderclass.yaml",
    "configmap.yaml",
    "db-schema-configmap.yaml",
    "service.yaml",
    "deployment.yaml",
    "web-deployment.yaml",
    "hpa.yaml",
    "networkpolicy-api.yaml",
    "networkpolicy-web.yaml",
    "default-domain-certificate.yaml",
    "https-gateway.yaml",
]

for name in files:
    shutil.copyfile(root / name, out / name)

import re

def replace_pattern(filename, pattern, replacement, expected=1):
    path = out / filename
    contents = path.read_text()

    updated, count = re.subn(
        pattern,
        replacement,
        contents,
        flags=re.MULTILINE
    )

    if count != expected:
        raise RuntimeError(
            f"{filename}: expected {expected} replacements, got {count}"
        )

    path.write_text(updated)

# Key Vault name
replace_pattern(
    "secretproviderclass.yaml",
    r'^([ \t]*keyvaultName:[ \t]*)["\']?[\w-]+["\']?[ \t]*$',
    lambda m: f'{m.group(1)}"{keyvault_name}"'
)

# Azure tenant
replace_pattern(
    "secretproviderclass.yaml",
    r'^([ \t]*tenantId:[ \t]*)["\']?[\w-]+["\']?[ \t]*$',
    lambda m: f'{m.group(1)}"{tenant_id}"'
)

# Workload Identity
replace_pattern(
    "serviceaccount.yaml",
    r'^([ \t]*azure\.workload\.identity/client-id:[ \t]*)["\']?[\w-]+["\']?[ \t]*$',
    lambda m: f'{m.group(1)}"{client_id}"'
)

replace_pattern(
    "secretproviderclass.yaml",
    r'^([ \t]*clientID:[ \t]*)["\']?[\w-]+["\']?[ \t]*$',
    lambda m: f'{m.group(1)}"{client_id}"'
)


# Container images
replace_pattern(
    "deployment.yaml",
    r'^([ \t]*image:[ \t]*)\S+/learningsteps-api:\S+',
    lambda m: (
        f"{m.group(1)}"
        f"{registry}/learningsteps-api:v0.7.0"
    )
)

replace_pattern(
    "web-deployment.yaml",
    r'^([ \t]*image:[ \t]*)\S+/learningsteps-web:\S+',
    lambda m: (
        f"{m.group(1)}"
        f"{registry}/learningsteps-web:v0.6.0-recovery-fix2"
    )
)


# Gateway and HTTPRoute hostname
replace_pattern(
    "https-gateway.yaml",
    r'^([ \t]*hostname:[ \t]*)learningsteps\.[^\s]+',
    lambda m: f"{m.group(1)}{hostname}"
)

replace_pattern(
    "https-gateway.yaml",
    r'^([ \t]*-[ \t]*)learningsteps\.[^\s]+',
    lambda m: f"{m.group(1)}{hostname}"
)

print(f"Prepared {len(files)} manifests")
print(f"Gateway hostname: {hostname}")
print(f"ACR: {registry}")
PY

echo "[6/6] Validating manifests"

echo "[VALIDATION] Checking Kubernetes schemas and YAML"

kubeconform \
  -strict \
  -summary \
  -ignore-missing-schemas \
  "$OUT_DIR/"

kubectl create \
  --dry-run=client \
  -f "$OUT_DIR/" \
  -o name

echo
echo "PASS: Recovery manifests prepared and client-side validated"
echo "Directory: $OUT_DIR"

if [[ "$MODE" == "--dry-run" ]]; then
  echo "DRY RUN: No Azure or Kubernetes resources were modified."
  exit 0
fi

# ----------------------------------------------------
# Bootstrap safety checks
# ----------------------------------------------------

echo "[BOOTSTRAP] Verifying cluster identity"

UID_FILE="$HOME/learningsteps-recovery/original-cluster-uid.txt"

if [[ ! -f "$UID_FILE" ]]; then
  echo "ERROR: Original cluster UID reference missing"
  exit 1
fi

ORIGINAL_UID="$(cat "$UID_FILE")"

CURRENT_UID="$(kubectl get namespace kube-system \
  -o jsonpath='{.metadata.uid}')"

if [[ -z "$ORIGINAL_UID" || -z "$CURRENT_UID" ]]; then
  echo "ERROR: Cluster UID is missing"
  exit 1
fi

if [[ "$ORIGINAL_UID" == "$CURRENT_UID" ]]; then
  echo "ERROR: Original AKS cluster detected."
  echo "Bootstrap is not permitted on the original cluster."
  exit 1
fi

echo "PASS: Cluster UID differs from original cluster"

# Recheck target immediately before modifying resources
CURRENT_CONTEXT="$(kubectl config current-context)"

if [[ "$CURRENT_CONTEXT" != "$AKS_NAME" ]]; then
  echo "ERROR: Unexpected kubectl context: $CURRENT_CONTEXT"
  exit 1
fi

# ----------------------------------------------------
# Guarded application recovery deployment
# ----------------------------------------------------

if [[ "$MODE" == "--deploy" ]]; then

  echo "[DEPLOY 1/7] Checking bootstrap resources"

  for resource in \
    "serviceaccount/learningsteps-api" \
    "configmap/learningsteps-config" \
    "configmap/learningsteps-db-schema" \
    "service/learningsteps-api" \
    "secretproviderclass/learningsteps-keyvault"; do

    kubectl get "$resource" -n "$NAMESPACE" >/dev/null || {
      echo "ERROR: Missing bootstrap resource: $resource"
      exit 1
    }
  done

  echo "[DEPLOY 2/7] Verifying restored PostgreSQL database"

  "$ROOT/scripts/recover-postgres.sh" --verify

  echo "[DEPLOY 3/7] Verifying ACR image availability"

  ACR_NAME="${ACR_LOGIN_SERVER%%.*}"
  ORIGINAL_ACR_FILE="$HOME/learningsteps-recovery/original-acr.json"

  [[ -s "$ORIGINAL_ACR_FILE" ]] || {
    echo "ERROR: Original ACR identity reference missing"
    exit 1
  }

  CURRENT_ACR_JSON="$(az acr show \
    --name "$ACR_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    -o json)"

  export CURRENT_ACR_JSON ORIGINAL_ACR_FILE ACR_LOGIN_SERVER

  python3 - <<'PY'
import json
import os
from datetime import datetime
from pathlib import Path

original = json.loads(
    Path(os.environ["ORIGINAL_ACR_FILE"]).read_text()
)
current = json.loads(os.environ["CURRENT_ACR_JSON"])

def timestamp(value):
    if not value:
        raise ValueError("Missing ACR creation timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

if current["loginServer"] != os.environ["ACR_LOGIN_SERVER"]:
    raise SystemExit("ERROR: Unexpected ACR endpoint")

if current["provisioningState"] != "Succeeded":
    raise SystemExit("ERROR: ACR is not ready")

if timestamp(current["creationDate"]) == timestamp(original["createdAt"]):
    raise SystemExit("ERROR: Original ACR detected")

print("PASS: New ACR generation verified")
PY

  for image in \
    "learningsteps-api:v0.7.0" \
    "learningsteps-web:v0.6.0-recovery-fix2"; do

    digest="$(az acr repository show \
      --name "$ACR_NAME" \
      --image "$image" \
      --query digest -o tsv)"

    [[ "$digest" == sha256:* ]] || {
      echo "ERROR: Missing or invalid image digest: $image"
      exit 1
    }

    echo "PASS: $image -> $digest"
  done

echo "[SECURITY] Verifying AKS kubelet ACR pull permission"

KUBELET_OBJECT_ID="$(az aks show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$AKS_NAME" \
  --query 'identityProfile.kubeletidentity.objectId' \
  -o tsv)"

ACR_RESOURCE_ID="$(az acr show \
  --name "$ACR_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query id \
  -o tsv)"

[[ -n "$KUBELET_OBJECT_ID" &&
   "$KUBELET_OBJECT_ID" != "None" ]] || {
  echo "ERROR: AKS kubelet identity missing"
  exit 1
}

[[ -n "$ACR_RESOURCE_ID" &&
   "$ACR_RESOURCE_ID" != "None" ]] || {
  echo "ERROR: ACR resource ID missing"
  exit 1
}

ROLE_ASSIGNMENTS="$(az role assignment list \
  --assignee "$KUBELET_OBJECT_ID" \
  --scope "$ACR_RESOURCE_ID" \
  --include-inherited \
  -o json)"

export ROLE_ASSIGNMENTS ACR_RESOURCE_ID KUBELET_OBJECT_ID

python3 - <<'PY'
import json
import os

assignments = json.loads(os.environ["ROLE_ASSIGNMENTS"])

expected_acr = os.environ["ACR_RESOURCE_ID"].lower()
expected_principal = os.environ["KUBELET_OBJECT_ID"].lower()

matches = []

for assignment in assignments:
    role = assignment.get("roleDefinitionName")
    principal = assignment.get("principalId", "").lower()
    scope = assignment.get("scope", "").lower().rstrip("/")

    if role != "AcrPull":
        continue

    if principal != expected_principal:
        continue

    if scope == expected_acr or expected_acr.startswith(scope + "/"):
        matches.append(assignment)

if not matches:
    raise SystemExit(
        "ERROR: Kubelet has no applicable AcrPull role"
    )

print("PASS: AKS kubelet AcrPull assignment verified")
PY

  echo "[DEPLOY 4/7] Checking existing application workloads"

  # Never overwrite existing deployments automatically.
  for deployment in learningsteps-api learningsteps-web; do
    if kubectl get deployment "$deployment" \
      -n "$NAMESPACE" -o name >/dev/null 2>&1; then
      echo "ERROR: Deployment already exists: $deployment"
      exit 1
    fi

    # Confirm that the namespace itself remains accessible.
    kubectl get namespace "$NAMESPACE" >/dev/null

    # Confirm deployment listing works before treating absence as safe.
    existing="$(kubectl get deployments \
      -n "$NAMESPACE" -o name)"

    if grep -Fxq "deployment.apps/$deployment" <<< "$existing"; then
      echo "ERROR: Deployment exists: $deployment"
      exit 1
    fi
  done

  echo
  echo "APPLICATION RECOVERY"
  echo "AKS: $AKS_NAME"
  echo "Namespace: $NAMESPACE"
  echo "ACR: $ACR_LOGIN_SERVER"
  echo "Database: Verified"
  echo
  echo "This will create Kubernetes application resources."
  echo

  [[ -t 0 ]] || {
    echo "ERROR: Interactive confirmation required"
    exit 1
  }

  read -r -p \
    "Type 'DEPLOY learningsteps' to continue: " CONFIRMATION

  [[ "$CONFIRMATION" == "DEPLOY learningsteps" ]] || {
    echo "Deployment cancelled"
    exit 1
  }

  echo "[SECURITY] Rechecking target immediately before deployment"

  [[ "$(az account show --query id -o tsv)" == \
      "$EXPECTED_SUBSCRIPTION" ]] || exit 1

  [[ "$(kubectl config current-context)" == "$AKS_NAME" ]] || exit 1

  NEW_UID="$(kubectl get namespace kube-system \
    -o jsonpath='{.metadata.uid}')"

  [[ -n "$NEW_UID" && "$NEW_UID" != "$ORIGINAL_UID" &&
     "$NEW_UID" == "$CURRENT_UID" ]] || {
    echo "ERROR: Cluster identity changed"
    exit 1
  }

  echo "[DEPLOY 5/7] Applying network and certificate resources"

  kubectl apply \
    -f "$OUT_DIR/networkpolicy-api.yaml" \
    -f "$OUT_DIR/networkpolicy-web.yaml"

  kubectl apply \
    -f "$OUT_DIR/default-domain-certificate.yaml"

  echo "[DEPLOY 6/7] Deploying API and Web"

  kubectl apply -f "$OUT_DIR/deployment.yaml"
  kubectl apply -f "$OUT_DIR/web-deployment.yaml"

  kubectl rollout status \
    deployment/learningsteps-api \
    -n "$NAMESPACE" \
    --timeout=300s

  kubectl rollout status \
    deployment/learningsteps-web \
    -n "$NAMESPACE" \
    --timeout=300s

  echo "[DEPLOY 7/7] Applying HPA and HTTPS gateway"

  kubectl apply -f "$OUT_DIR/hpa.yaml"
  kubectl apply -f "$OUT_DIR/https-gateway.yaml"

  echo
  echo "PASS: Kubernetes application resources applied"
  echo "NOTE: HTTPS, Entra ID login and application functionality"
  echo "still require separate end-to-end verification."

  exit 0
fi

echo
echo "TARGET: $RESOURCE_GROUP / $AKS_NAME"
echo "NAMESPACE: $NAMESPACE"
echo "ACTION: Create Kubernetes recovery base resources"
echo
echo "No API Deployment, Web Deployment or database restore"
echo "will be performed."
echo

if [[ ! -t 0 ]]; then
  echo "ERROR: Interactive confirmation required"
  exit 1
fi

read -r -p \
  "Type 'BOOTSTRAP aks-learningsteps' to continue: " \
  CONFIRMATION

if [[ "$CONFIRMATION" != "BOOTSTRAP aks-learningsteps" ]]; then
  echo "Bootstrap cancelled"
  exit 1
fi

echo "[BOOTSTRAP] Creating namespace"

kubectl apply -f "$OUT_DIR/namespace.yaml"

echo "[BOOTSTRAP] Creating identity and configuration"

kubectl apply \
  -f "$OUT_DIR/serviceaccount.yaml" \
  -f "$OUT_DIR/secretproviderclass.yaml" \
  -f "$OUT_DIR/configmap.yaml" \
  -f "$OUT_DIR/db-schema-configmap.yaml"

echo "[BOOTSTRAP] Creating API service"

kubectl apply -f "$OUT_DIR/service.yaml"

echo
echo "PASS: Kubernetes base resources applied"
echo "STOP: PostgreSQL recovery must be completed next"
