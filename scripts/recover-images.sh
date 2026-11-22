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
   [[ "$MODE" != "--dry-run" &&
      "$MODE" != "--build" &&
      "$MODE" != "--push" ]]; then
  echo "Usage: $0 [--dry-run|--build|--push]"
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
# Guarded ACR recovery push
# ----------------------------------------------------

if [[ "$MODE" == "--push" ]]; then
  echo "[PUSH 1/6] Verifying target ACR generation"

  ORIGINAL_ACR_FILE="$HOME/learningsteps-recovery/original-acr.json"

  [[ -s "$ORIGINAL_ACR_FILE" ]] || {
    echo "ERROR: Original ACR reference missing"
    exit 1
  }

  ACR_NAME="${ACR%%.*}"

verify_acr_generation() {
  local current_acr_json

  current_acr_json="$(az acr show \
    --name "$ACR_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    -o json)"

  CURRENT_ACR_JSON="$current_acr_json" \
  ORIGINAL_ACR_FILE="$ORIGINAL_ACR_FILE" \
  EXPECTED_ACR="$ACR" \
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
    if not isinstance(value, str) or not value:
        raise ValueError("ACR creation timestamp missing")

    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

if current["loginServer"] != os.environ["EXPECTED_ACR"]:
    raise SystemExit("ERROR: Unexpected ACR login server")

if current["provisioningState"] != "Succeeded":
    raise SystemExit("ERROR: Target ACR is not ready")

if current["adminUserEnabled"] is not False:
    raise SystemExit("ERROR: ACR admin account is enabled")

if timestamp(current["creationDate"]) == timestamp(
    original["createdAt"]
):
    raise SystemExit(
        "ERROR: Original ACR detected. Push prohibited."
    )

print("PASS: Target ACR generation verified")
PY
}

verify_acr_generation

  echo "[PUSH 2/6] Verifying local images"

  LOCAL_API_IMAGE="learningsteps-recovery-api:$API_TAG"
  LOCAL_WEB_IMAGE="learningsteps-recovery-web:$WEB_TAG"

  API_ID="$(docker image inspect \
    --format '{{.Id}}' "$LOCAL_API_IMAGE")"

  WEB_ID="$(docker image inspect \
    --format '{{.Id}}' "$LOCAL_WEB_IMAGE")"

  echo "API Image ID: $API_ID"
  echo "Web Image ID: $WEB_ID"

  echo "[PUSH 3/6] Running mandatory security scans"

  command -v trivy >/dev/null || {
    echo "ERROR: Trivy is required"
    exit 1
  }

  for image in "$LOCAL_API_IMAGE" "$LOCAL_WEB_IMAGE"; do
    trivy image \
      --scanners vuln \
      --severity HIGH,CRITICAL \
      --exit-code 1 \
      --ignore-unfixed=false \
      "$image"
  done

  [[ "$(docker image inspect --format '{{.Id}}' \
      "$LOCAL_API_IMAGE")" == "$API_ID" ]] || {
    echo "ERROR: API image changed during scan"
    exit 1
  }

  [[ "$(docker image inspect --format '{{.Id}}' \
      "$LOCAL_WEB_IMAGE")" == "$WEB_ID" ]] || {
    echo "ERROR: Web image changed during scan"
    exit 1
  }

  echo "PASS: Images passed security checks"

  API_TARGET="$ACR/learningsteps-api:$API_TAG"
  WEB_TARGET="$ACR/learningsteps-web:$WEB_TAG"

  check_remote_tags() {
    local repositories repository tag tags

    repositories="$(az acr repository list \
      --name "$ACR_NAME" -o json)"

    for specification in \
      "learningsteps-api:$API_TAG" \
      "learningsteps-web:$WEB_TAG"; do

      repository="${specification%%:*}"
      tag="${specification#*:}"

      if python3 -c \
        'import json,sys; sys.exit(0 if sys.argv[1] in json.load(sys.stdin) else 1)' \
        "$repository" <<< "$repositories"; then

        tags="$(az acr repository show-tags \
          --name "$ACR_NAME" \
          --repository "$repository" \
          -o json)"

        if python3 -c \
          'import json,sys; sys.exit(0 if sys.argv[1] in json.load(sys.stdin) else 1)' \
          "$tag" <<< "$tags"; then
          echo "ERROR: Target tag already exists: $repository:$tag"
          return 1
        fi
      fi
    done

    echo "PASS: Target image tags are not present"
  }

  echo "[PUSH 4/6] Checking target tags"
  check_remote_tags

  echo
  echo "ACR RECOVERY PUSH"
  echo "Registry: $ACR"
  echo "API:      $API_TARGET"
  echo "Web:      $WEB_TARGET"
  echo

  if [[ ! -t 0 ]]; then
    echo "ERROR: Interactive confirmation required"
    exit 1
  fi

  read -r -p \
    "Type 'PUSH RECOVERY IMAGES' to continue: " CONFIRMATION

  if [[ "$CONFIRMATION" != "PUSH RECOVERY IMAGES" ]]; then
    echo "Push cancelled"
    exit 1
  fi

  echo "[PUSH 5/6] Authenticating and uploading"

  echo "[SECURITY] Rechecking Azure subscription"

  CURRENT_SUBSCRIPTION="$(az account show --query id -o tsv)"

  if [[ "$CURRENT_SUBSCRIPTION" != "$EXPECTED_SUBSCRIPTION" ]]; then
    echo "ERROR: Azure subscription changed"
    exit 1
  fi

  echo "[SECURITY] Rechecking target ACR generation"
  verify_acr_generation

  az acr login --name "$ACR_NAME"

  echo "[SECURITY] Rechecking target tags"
  check_remote_tags

  docker tag "$API_ID" "$API_TARGET"
  docker tag "$WEB_ID" "$WEB_TARGET"

  [[ "$(docker image inspect --format '{{.Id}}' \
      "$API_TARGET")" == "$API_ID" ]] || exit 1

  [[ "$(docker image inspect --format '{{.Id}}' \
      "$WEB_TARGET")" == "$WEB_ID" ]] || exit 1

  docker push "$API_TARGET"
  docker push "$WEB_TARGET"

  echo "[PUSH 6/6] Reading registry digests"

  az acr repository show \
    --name "$ACR_NAME" \
    --image "learningsteps-api:$API_TAG" \
    --query '{digest:digest,createdTime:createdTime}' \
    -o json

  az acr repository show \
    --name "$ACR_NAME" \
    --image "learningsteps-web:$WEB_TAG" \
    --query '{digest:digest,createdTime:createdTime}' \
    -o json

  echo
  echo "PASS: Recovery images pushed to ACR"
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
