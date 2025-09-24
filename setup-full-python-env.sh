#!/usr/bin/env bash
# AlmaLinux 9: install Python 3.11 only (no venv, no deps)
set -euo pipefail

echo ">>> Ensuring CRB repo is enabled (required for python3.11 on Alma 9)..."
if ! sudo dnf repolist --enabled | awk '{print $1}' | grep -qx crb; then
  sudo dnf -y install dnf-plugins-core >/dev/null 2>&1 || true
  sudo dnf config-manager --set-enabled crb
  sudo dnf -y makecache --refresh
fi

echo ">>> Installing Python 3.11 ..."
sudo dnf -y install python3.11

# Verify
if ! command -v /usr/bin/python3.11 >/dev/null 2>&1; then
  echo "ERROR: /usr/bin/python3.11 not found after install." >&2
  exit 1
fi

echo ">>> Installed: $(/usr/bin/python3.11 -V)"
echo ">>> Use it explicitly as: /usr/bin/python3.11"
