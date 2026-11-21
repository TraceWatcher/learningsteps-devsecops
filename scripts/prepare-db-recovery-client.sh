#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RESOURCE_GROUP="rg-learningsteps-devsecops"
POSTGRES_NAME="psql-learningsteps-305c3ba6"

SOURCE="$ROOT/k8s-manifests/db-recovery-client.yaml"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 OUTPUT_FILE"
  exit 2
fi

OUTPUT="$1"

[[ -f "$SOURCE" ]] || {
  echo "ERROR: Source manifest missing"
  exit 1
}

command -v az >/dev/null
command -v kubectl >/dev/null
command -v python3 >/dev/null

echo "[1/3] Resolving PostgreSQL hostname"

PG_HOST="$(az postgres flexible-server show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$POSTGRES_NAME" \
  --query fullyQualifiedDomainName \
  -o tsv)"

if [[ "$PG_HOST" != *.postgres.database.azure.com ]]; then
  echo "ERROR: Unexpected PostgreSQL hostname"
  exit 1
fi

echo "[2/3] Preparing recovery client manifest"

export SOURCE OUTPUT PG_HOST

python3 - <<'PY'
import os
import re
from pathlib import Path

source = Path(os.environ["SOURCE"])
output = Path(os.environ["OUTPUT"])

if source.resolve() == output.resolve():
    raise SystemExit("ERROR: Source and output must differ")

content = source.read_text()

pattern = (
    r'^([ \t]*-[ \t]*name:[ \t]*PGHOST[ \t]*\n'
    r'[ \t]*value:[ \t]*)[^\n]+'
)

updated, count = re.subn(
    pattern,
    lambda m: f'{m.group(1)}"{os.environ["PG_HOST"]}"',
    content,
    flags=re.MULTILINE
)

if count != 1:
    raise SystemExit(
        f"ERROR: Expected one PGHOST value, found {count}"
    )

output.write_text(updated)
PY

echo "[3/3] Validating manifest"

kubectl create \
  --dry-run=client \
  --validate=false \
  -f "$OUTPUT" \
  -o name

echo
echo "PASS: PostgreSQL recovery client prepared"
echo "PostgreSQL host: $PG_HOST"
echo "Manifest: $OUTPUT"
echo "No Kubernetes resources were modified."
