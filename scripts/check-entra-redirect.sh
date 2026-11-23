#!/usr/bin/env bash
set -euo pipefail

EXPECTED_SUB="901cb597-1248-4bc6-8b92-0452114c48b9"
RG="rg-learningsteps-devsecops"
AKS="aks-learningsteps"

# Existing LearningSteps frontend app registration
APP_ID="0ff6b105-66c2-4848-99ac-0f57a375d499"

echo "[1/4] Checking Azure subscription"

[[ "$(az account show --query id -o tsv)" == "$EXPECTED_SUB" ]] || {
  echo "FAIL: Wrong Azure subscription"
  exit 1
}

echo "[2/4] Reading AKS default domain"

DOMAIN="$(az aks approuting defaultdomain show \
  -g "$RG" -n "$AKS" \
  --query domainName -o tsv)"

[[ -n "$DOMAIN" && "$DOMAIN" != "None" ]] || {
  echo "FAIL: AKS default domain unavailable"
  exit 1
}

REDIRECT_URI="https://learningsteps.${DOMAIN}/"

echo "[3/4] Checking Entra ID application"

APP_JSON="$(az ad app show --id "$APP_ID" \
  --query '{appId:appId,spaRedirects:spa.redirectUris}' \
  -o json)"

echo "[4/4] Verifying SPA redirect URI"

export APP_JSON REDIRECT_URI APP_ID

python3 - <<'PY'
import json
import os

app = json.loads(os.environ["APP_JSON"])
expected = os.environ["REDIRECT_URI"]

if app.get("appId") != os.environ["APP_ID"]:
    raise SystemExit("FAIL: Unexpected application")

redirects = app.get("spaRedirects") or []

if expected not in redirects:
    print("FAIL: Missing SPA redirect URI")
    print(f"Required: {expected}")
    raise SystemExit(1)

print()
print("PASS: Entra ID SPA redirect URI verified")
print(f"Redirect URI: {expected}")
print("No Entra ID settings were modified.")
PY
