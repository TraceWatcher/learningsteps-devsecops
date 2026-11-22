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

echo "[SECURITY] Checking maintenance VM power state"

VM_STATE="$(az vm get-instance-view \
  --resource-group rg-learningsteps-devsecops \
  --name learningsteps-maintenance \
  --query 'instanceView.statuses[?starts_with(code, `PowerState/`)].code' \
  -o tsv)"

if [[ "$VM_STATE" != "PowerState/running" ]]; then
  echo "ERROR: Recovery VM must be running"
  exit 1
fi

echo "PASS: Recovery VM is running"

echo "[3/4] Verifying PostgreSQL recovery target"

"$ROOT/scripts/recover-postgres.sh" --check-target

echo "[4/4] Checking Key Vault infrastructure"

"$ROOT/scripts/recover-keyvault.sh" --inspect-target

echo
echo "PASS: Transport preflight completed"
echo "INFO: This does not authorize secret restoration"
echo "INFO: No secrets were transferred"
