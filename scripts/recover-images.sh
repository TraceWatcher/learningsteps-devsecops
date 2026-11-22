#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

EXPECTED_SUBSCRIPTION="901cb597-1248-4bc6-8b92-0452114c48b9"
RESOURCE_GROUP="rg-learningsteps-devsecops"

API_REF="v0.7.0"
WEB_REF="a756d3c"

API_TAG="v0.7.0"
WEB_TAG="v0.6.0-recovery"

MODE="${1:---dry-run}"

if [[ $# -gt 1 ]] ||
   [[ "$MODE" != "--dry-run" && "$MODE" != "--build" ]]; then
  echo "Usage: $0 [--dry-run|--build]"
  exit 2
fi

echo "[1/5] Checking dependencies"

for tool in git docker az python3; do
  command -v "$tool" >/dev/null || {
    echo "ERROR: Missing dependency: $tool"
    exit 1
  }
done

echo "[2/5] Checking Azure subscription"

SUBSCRIPTION="$(az account show --query id -o tsv)"

[[ "$SUBSCRIPTION" == "$EXPECTED_SUBSCRIPTION" ]] || {
  echo "ERROR: Unexpected Azure subscription"
  exit 1
}

echo "PASS: Correct Azure subscription"

echo "[3/5] Resolving Azure Container Registry"

mapfile -t ACR_SERVERS < <(
  az acr list \
    --resource-group "$RESOURCE_GROUP" \
    --query '[].loginServer' \
    -o tsv
)

if [[ "${#ACR_SERVERS[@]}" -ne 1 ]]; then
  echo "ERROR: Expected exactly one ACR"
  exit 1
fi

ACR="${ACR_SERVERS[0]}"

[[ "$ACR" == *.azurecr.io ]] || {
  echo "ERROR: Invalid ACR login server"
  exit 1
}

echo "PASS: ACR resolved: $ACR"

echo "[4/5] Checking Git recovery sources"

for ref in "$API_REF" "$WEB_REF"; do
  git -C "$ROOT" rev-parse --verify "${ref}^{commit}" >/dev/null
done

git -C "$ROOT" cat-file -e "$API_REF:Dockerfile"
git -C "$ROOT" cat-file -e "$API_REF:api/requirements.txt"

git -C "$ROOT" cat-file -e "$WEB_REF:web/Dockerfile"
git -C "$ROOT" cat-file -e "$WEB_REF:web/package-lock.json"
git -C "$ROOT" cat-file -e "$WEB_REF:web/nginx.conf"

API_COMMIT="$(git -C "$ROOT" rev-parse "$API_REF^{commit}")"
WEB_COMMIT="$(git -C "$ROOT" rev-parse "$WEB_REF^{commit}")"

echo "PASS: Recovery sources available"

echo "[5/5] Checking Docker"

docker info --format '{{.ServerVersion}}' >/dev/null

echo "PASS: Docker daemon available"

echo
echo "=== Recovery image plan ==="
echo "API source: $API_COMMIT"
echo "Web source: $WEB_COMMIT"
echo
echo "API image: $ACR/learningsteps-api:$API_TAG"
echo "Web image: $ACR/learningsteps-web:$WEB_TAG"
echo
echo "PASS: Image recovery preflight completed"

if [[ "$MODE" == "--dry-run" ]]; then
  echo "No Docker images were built or pushed."
  echo "No Azure or Kubernetes resources were modified."
  exit 0
fi

# ----------------------------------------------------
# Local recovery builds
# ----------------------------------------------------

LOCAL_API_IMAGE="learningsteps-recovery-api:$API_TAG"
LOCAL_WEB_IMAGE="learningsteps-recovery-web:$WEB_TAG"

BUILD_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "$BUILD_DIR"
}

trap cleanup EXIT

mkdir -p \
  "$BUILD_DIR/api" \
  "$BUILD_DIR/web"

echo
echo "[BUILD 1/4] Exporting Git release sources"

git -C "$ROOT" archive "$API_REF" |
  tar -x -C "$BUILD_DIR/api"

git -C "$ROOT" archive "$WEB_REF" web/ |
  tar -x -C "$BUILD_DIR/web"

test -f "$BUILD_DIR/api/Dockerfile"
test -f "$BUILD_DIR/web/web/Dockerfile"

echo "[BUILD] Applying Web runtime security patch"

python3 - "$BUILD_DIR/web/web/Dockerfile" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
content = path.read_text()

old = "FROM nginx/nginx-unprivileged:stable-alpine"
new = """FROM nginx/nginx-unprivileged:stable-alpine

# Apply security updates during recovery image build
USER root
RUN apk upgrade --no-cache
USER 101"""

if content.count(old) != 1:
    raise SystemExit("ERROR: Unexpected Web runtime base image")

path.write_text(content.replace(old, new))

print("PASS: Web runtime security patch applied")
PY

echo "PASS: Both source trees exported"

echo "[BUILD 2/4] Building API image"

docker build \
  --build-arg "APP_VERSION=$API_TAG" \
  --tag "$LOCAL_API_IMAGE" \
  "$BUILD_DIR/api"

echo "[BUILD 3/4] Building Web image"

docker build \
  --tag "$LOCAL_WEB_IMAGE" \
  "$BUILD_DIR/web/web"

echo "[BUILD 4/4] Verifying local images"

echo "[SECURITY] Checking Trivy availability"

command -v trivy >/dev/null || {
  echo "ERROR: Trivy is required for recovery builds"
  exit 1
}

echo "[SECURITY] Scanning API image"

trivy image \
  --scanners vuln \
  --severity HIGH,CRITICAL \
  --exit-code 1 \
  --ignore-unfixed=false \
  "$LOCAL_API_IMAGE"

echo "[SECURITY] Scanning Web image"

trivy image \
  --scanners vuln \
  --severity HIGH,CRITICAL \
  --exit-code 1 \
  --ignore-unfixed=false \
  "$LOCAL_WEB_IMAGE"

echo "PASS: Both recovery images passed security scans"

docker image inspect \
  "$LOCAL_API_IMAGE" \
  "$LOCAL_WEB_IMAGE" \
  --format '{{.RepoTags}} {{.Id}}'

echo
echo "PASS: Both recovery images built locally"
echo "API: $LOCAL_API_IMAGE"
echo "Web: $LOCAL_WEB_IMAGE"
echo
echo "No images were pushed to Azure."
echo "No Kubernetes resources were modified."
