#!/usr/bin/env bash
set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || {
  echo "ERROR: Run as root"
  exit 1
}

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y --no-install-recommends \
  age \
  python3 \
  ca-certificates \
  curl

command -v age >/dev/null
command -v age-keygen >/dev/null
command -v python3 >/dev/null

echo "PASS: Recovery tools installed"

age --version
python3 --version
