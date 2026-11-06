#!/usr/bin/env bash
# 更柝 Vigiliae · one-command installer
#
#   curl -sSL https://trustbaselab.com/vigiliae-install.sh | bash
#
# Env:
#   VIGILIAE_PREFIX   install root (default /opt/vigiliae)
#   VIGILIAE_TARBALL  override source tarball (useful for mirrors/offline)
#   PYTHON            python binary (default python3)
#
# The actual heavy lifting is in vigiliae/install.py, so it can be tested
# independently on Windows/Linux without this shell wrapper.
set -euo pipefail

PREFIX="${VIGILIAE_PREFIX:-/opt/vigiliae}"
TARBALL="${VIGILIAE_TARBALL:-https://github.com/Trustbaselab/vigiliae/archive/refs/heads/main.tar.gz}"
PYTHON="${PYTHON:-python3}"

command -v "$PYTHON" >/dev/null 2>&1 || {
  echo "ERROR: $PYTHON not found; install Python 3.9+ first" >&2
  exit 1
}
command -v curl >/dev/null 2>&1 || {
  echo "ERROR: curl not found; install curl first" >&2
  exit 1
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "[vigiliae-install] downloading $TARBALL"
curl -fsSL "$TARBALL" | tar -xz -C "$TMP"

SRC="$(find "$TMP" -maxdepth 1 -mindepth 1 -type d | head -n 1)"
[ -n "$SRC" ] || { echo "ERROR: empty tarball" >&2; exit 1; }
cd "$SRC"

# If /opt is not writable and we are not root, try sudo once.
SUDO=""
if [ "$(id -u)" -ne 0 ] && [ ! -w "$(dirname "$PREFIX")" ]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    echo "ERROR: no write permission to $(dirname "$PREFIX"); rerun as root or set VIGILIAE_PREFIX=$HOME/vigiliae" >&2
    exit 1
  fi
fi

echo "[vigiliae-install] installing to $PREFIX"
$SUDO "$PYTHON" -m vigiliae.install --prefix "$PREFIX" "$@"
