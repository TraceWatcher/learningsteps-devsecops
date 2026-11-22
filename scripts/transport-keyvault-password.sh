#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP="$HOME/learningsteps-recovery"
RG="rg-learningsteps-devsecops"
VM="learningsteps-maintenance"

[[ "${1:-}" == "--transfer" && $# -eq 1 ]] || {
  echo "Usage: $0 --transfer" >&2
  exit 2
}

for tool in az age base64 python3 sha256sum; do
  command -v "$tool" >/dev/null || {
    echo "ERROR: Missing command: $tool" >&2
    exit 1
  }
done

for file in \
  "$BACKUP/backup-key.txt" \
  "$BACKUP/postgres-admin-password.age"; do
  [[ -s "$file" ]] || {
    echo "ERROR: Missing recovery file: $file" >&2
    exit 1
  }
done

echo "[1/5] Recording target VM identity"

BEFORE="$(az vm show \
  -g "$RG" -n "$VM" \
  --query '{vmId:vmId,principalId:identity.principalId}' \
  -o json)"

echo "[2/5] Checking recovery target and generating recipient"

RECIPIENT_OUTPUT="$(
  "$ROOT/scripts/recover-keyvault-controller.sh" \
    --prepare-recipient
)"

RECIPIENT="$(printf '%s\n' "$RECIPIENT_OUTPUT" |
  grep -E '^RECIPIENT=age1[0-9a-z]+$' |
  cut -d= -f2)"

[[ "$(printf '%s\n' "$RECIPIENT" | grep -Ec '^age1[0-9a-z]+$')" -eq 1 ]] || {
  echo "ERROR: Invalid recipient" >&2
  exit 1
}

echo "[3/5] Re-encrypting PostgreSQL password locally"

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TEMP_DIR"' EXIT

CIPHER="$TEMP_DIR/postgres-admin-password.age"

age --decrypt \
  --identity "$BACKUP/backup-key.txt" \
  "$BACKUP/postgres-admin-password.age" |
age --encrypt \
  --recipient "$RECIPIENT" \
  --output "$CIPHER"

[[ -s "$CIPHER" ]] || {
  echo "ERROR: Empty ciphertext" >&2
  exit 1
}

EXPECTED_SHA="$(sha256sum "$CIPHER" | cut -d' ' -f1)"
CIPHER_B64="$(base64 -w 0 "$CIPHER")"

echo "[4/5] Transferring encrypted password"

REMOTE_SCRIPT="$(cat <<SCRIPT
set +e
(
  set -eu
  umask 077

  DIR="/var/lib/learningsteps-recovery"
  TARGET="\$DIR/postgres-admin-password.age"

  test -f "\$DIR/recipient-identity.txt"

  TMP="\$(mktemp "\$DIR/.password-XXXXXXXX")"
  trap 'rm -f -- "\$TMP"' EXIT

  printf '%s' '$CIPHER_B64' | base64 -d > "\$TMP"

  ACTUAL="\$(sha256sum "\$TMP" | cut -d' ' -f1)"
  test "\$ACTUAL" = "$EXPECTED_SHA"

  # Confirm that the VM's private AGE identity can decrypt it.
  age --decrypt \
    --identity "\$DIR/recipient-identity.txt" \
    --output /dev/null \
    "\$TMP"

  chmod 600 "\$TMP"

  if test -e "\$TARGET" || test -L "\$TARGET"; then
    test ! -L "\$TARGET"
    test -f "\$TARGET"
    test "\$(stat -c %u "\$TARGET")" = "0"
    test "\$(stat -c %a "\$TARGET")" = "600"

    python3 -c '
import hmac
import subprocess
import sys

identity, existing, incoming = sys.argv[1:]

def decrypt(path):
    result = subprocess.run(
        ["age", "--decrypt", "--identity", identity, path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout

old = decrypt(existing)
new = decrypt(incoming)

if not old or not hmac.compare_digest(old, new):
    raise SystemExit("ERROR: Existing recovery password differs")

print("PASS: Existing encrypted password verified")
' "\$DIR/recipient-identity.txt" "\$TARGET" "\$TMP"

    echo "PASS: Existing encrypted password retained"
    exit 0
  fi

  ln "\$TMP" "\$TARGET"

  test "\$(sha256sum "\$TARGET" | cut -d' ' -f1)" = "$EXPECTED_SHA"

  echo "PASS: Encrypted password stored"
)
rc=\$?
printf '__LS_TRANSPORT_RC__=%s\n' "\$rc"
exit 0
SCRIPT
)"

RESULT="$(az vm run-command invoke \
  --resource-group "$RG" \
  --name "$VM" \
  --command-id RunShellScript \
  --scripts "$REMOTE_SCRIPT" \
  -o json)"

echo "[5/5] Verifying transport and VM identity"

AFTER="$(az vm show \
  -g "$RG" -n "$VM" \
  --query '{vmId:vmId,principalId:identity.principalId}' \
  -o json)"

export BEFORE AFTER RESULT

python3 - <<'PY'
import json
import os
import re

before = json.loads(os.environ["BEFORE"])
after = json.loads(os.environ["AFTER"])
result = json.loads(os.environ["RESULT"])

for field in ("vmId", "principalId"):
    if not before.get(field) or not after.get(field):
        raise SystemExit("ERROR: Incomplete VM identity")

if before != after:
    raise SystemExit("ERROR: VM identity changed during transport")

entries = result.get("value", [])
if len(entries) != 1:
    raise SystemExit("ERROR: Unexpected Run Command response")

entry = entries[0]
if entry.get("code") != "ProvisioningState/succeeded":
    raise SystemExit("ERROR: Azure Run Command failed")

message = entry.get("message", "")
stdout = message.split("[stdout]", 1)[-1].split("[stderr]", 1)[0]

codes = re.findall(
    r"(?m)^__LS_TRANSPORT_RC__=(\d+)\s*$", stdout
)

if codes != ["0"]:
    raise SystemExit("ERROR: Remote transport failed")

success_messages = (
    "PASS: Encrypted password stored",
    "PASS: Existing encrypted password retained",
)

if not any(message in stdout for message in success_messages):
    raise SystemExit("ERROR: Missing transport confirmation")

print("PASS: VM identity unchanged")
print("PASS: Encrypted password transferred and verified")
print("INFO: Secret was not written to Key Vault")
PY
