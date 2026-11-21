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

if [[ "${1:---dry-run}" != "--dry-run" || $# -gt 1 ]]; then
  echo "ERROR: Only --dry-run is supported."
  exit 2
fi

for tool in az kubectl terraform python3; do
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
        f"{registry}/learningsteps-web:v0.6.0"
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

kubectl create \
  --dry-run=client \
  -f "$OUT_DIR/" \
  -o name

echo
echo "PASS: Recovery manifests prepared and client-side validated"
echo "Directory: $OUT_DIR"
echo "No Azure or Kubernetes resources were modified."
