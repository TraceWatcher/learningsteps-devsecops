#!/usr/bin/env bash
set -euo pipefail
umask 077

BACKUP_DIR="$HOME/learningsteps-recovery"

for command in age age-keygen python3; do
  command -v "$command" >/dev/null || {
    echo "ERROR: Required command missing: $command"
    exit 1
  }
done

ORIGINAL_KEY="$BACKUP_DIR/backup-key.txt"
ORIGINAL_BACKUP="$BACKUP_DIR/postgres-admin-password.age"

[[ -s "$ORIGINAL_KEY" && -s "$ORIGINAL_BACKUP" ]] || {
  echo "ERROR: Required AGE recovery files missing"
  exit 1
}

TEST_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TEST_DIR"' EXIT

KEY_HASH_BEFORE="$(sha256sum "$ORIGINAL_KEY" | cut -d' ' -f1)"

echo "[1/4] Generating temporary recipient"

age-keygen -o "$TEST_DIR/recipient-key.txt" 2>/dev/null
RECIPIENT="$(age-keygen -y "$TEST_DIR/recipient-key.txt")"

echo "[2/4] Re-encrypting password"

age --decrypt \
  --identity "$ORIGINAL_KEY" \
  "$ORIGINAL_BACKUP" |
age -r "$RECIPIENT" \
  -o "$TEST_DIR/password-reencrypted.age"

echo "[3/4] Verifying transported password"

python3 - \
  "$ORIGINAL_KEY" \
  "$ORIGINAL_BACKUP" \
  "$TEST_DIR/recipient-key.txt" \
  "$TEST_DIR/password-reencrypted.age" <<'PY'
import hmac
import subprocess
import sys

original_key, original_backup, new_key, new_backup = sys.argv[1:]

def decrypt(identity, encrypted_file):
    return subprocess.run(
        [
            "age", "--decrypt",
            "--identity", identity,
            encrypted_file
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout

original = decrypt(original_key, original_backup)
recovered = decrypt(new_key, new_backup)

if not original:
    raise SystemExit("ERROR: Empty password")

if not hmac.compare_digest(original, recovered):
    raise SystemExit("ERROR: Password mismatch")

print("PASS: Password recovered byte-for-byte")
PY

echo "[4/4] Verifying original key integrity"

KEY_HASH_AFTER="$(sha256sum "$ORIGINAL_KEY" | cut -d' ' -f1)"

[[ "$KEY_HASH_BEFORE" == "$KEY_HASH_AFTER" ]] || {
  echo "ERROR: Original AGE identity changed"
  exit 1
}

echo "PASS: Original AGE identity unchanged"
echo "PASS: No plaintext password written to disk"
