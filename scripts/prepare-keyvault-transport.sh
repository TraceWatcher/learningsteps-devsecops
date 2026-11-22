#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$HOME/learningsteps-recovery"

[[ $# -eq 0 ]] || {
  echo "Usage: $0"
  exit 2
}

echo "[1/4] Checking encrypted password backup"

for file in \
  "$BACKUP_DIR/postgres-admin-password.age" \
  "$BACKUP_DIR/backup-key.txt" \
  "$BACKUP_DIR/original-maintenance-vm.json" \
  "$BACKUP_DIR/original-postgres.json"; do

  [[ -s "$file" ]] || {
    echo "ERROR: Missing recovery artifact: $file"
    exit 1
  }
done

echo "PASS: Required recovery files exist"

echo "[2/4] Verifying new maintenance VM"

"$ROOT/scripts/check-recovery-vm.sh"

echo "[3/4] Verifying PostgreSQL recovery target"

"$ROOT/scripts/recover-postgres.sh" --check-target

echo "[4/4] Checking Key Vault infrastructure"

"$ROOT/scripts/recover-keyvault.sh" --inspect-target

echo
echo "PASS: Transport preflight completed"
echo "INFO: This does not authorize secret restoration"
echo "INFO: No secrets were transferred"
