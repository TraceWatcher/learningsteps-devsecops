#!/usr/bin/env bash
set -euo pipefail

EXPECTED_SUB="901cb597-1248-4bc6-8b92-0452114c48b9"
RG="rg-learningsteps-devsecops"
AKS="aks-learningsteps"
NAMESPACE="learningsteps"

echo "[1/6] Checking Azure subscription"

[[ "$(az account show --query id -o tsv)" == "$EXPECTED_SUB" ]] || {
  echo "FAIL: Wrong subscription"
  exit 1
}

echo "[2/6] Checking AKS context and endpoint"

[[ "$(kubectl config current-context)" == "$AKS" ]] || {
  echo "FAIL: Wrong Kubernetes context"
  exit 1
}

AKS_FQDN="$(az aks show -g "$RG" -n "$AKS" --query fqdn -o tsv)"
CURRENT_SERVER="$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')"

[[ "$CURRENT_SERVER" == "https://${AKS_FQDN}:443" ||
   "$CURRENT_SERVER" == "https://${AKS_FQDN}" ]] || {
  echo "FAIL: Kubernetes API endpoint mismatch"
  exit 1
}

echo "[3/6] Checking App Routing"

ROUTING="$(az aks show -g "$RG" -n "$AKS" \
  --query ingressProfile.webAppRouting.enabled -o tsv)"

[[ "${ROUTING,,}" == "true" ]] || {
  echo "FAIL: App Routing disabled"
  exit 1
}

echo "[4/6] Checking Default Domain"

DOMAIN="$(az aks approuting defaultdomain show \
  -g "$RG" -n "$AKS" \
  --query domainName -o tsv)"

[[ "$DOMAIN" == *.westeurope.aksapp.io ]] || {
  echo "FAIL: Default domain unavailable"
  exit 1
}

echo "[5/6] Checking Gateway API"

kubectl get crd gateways.gateway.networking.k8s.io >/dev/null

CLASS_ACCEPTED="$(kubectl get gatewayclass approuting-istio \
  -o jsonpath='{.status.conditions[?(@.type=="Accepted")].status}')"

[[ "$CLASS_ACCEPTED" == "True" ]] || {
  echo "FAIL: Istio GatewayClass not accepted"
  exit 1
}

echo "[6/6] Checking subscription feature"

FEATURE="$(az feature show \
  --namespace Microsoft.ContainerService \
  --name DefaultDomainPreview \
  --query properties.state -o tsv)"

[[ "$FEATURE" == "Registered" ]] || {
  echo "FAIL: DefaultDomainPreview not registered"
  exit 1
}

echo
echo "PASS: AKS routing prerequisites verified"
echo "Domain: $DOMAIN"
echo "No Azure or Kubernetes resources modified."
