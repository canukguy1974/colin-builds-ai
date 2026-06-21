#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

log() {
  printf '\n[AI Trend Radar] %s\n' "$1"
}

install_system_packages() {
  local packages=(python3 python3-venv python3-pip git)

  if ! command -v apt-get >/dev/null 2>&1; then
    echo "Automatic package installation currently supports Ubuntu/Debian-based WSL distributions."
    echo "Install Python 3, python3-venv, pip, and Git manually, then rerun this script."
    exit 1
  fi

  log "Installing required WSL packages"
  sudo apt-get update
  sudo apt-get install -y "${packages[@]}"
}

if ! command -v python3 >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1; then
  install_system_packages
fi

if ! python3 - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
then
  echo "Python 3.10 or newer is required."
  python3 --version || true
  exit 1
fi

if ! python3 -m venv --help >/dev/null 2>&1; then
  install_system_packages
fi

if [[ ! -d .venv ]]; then
  log "Creating Python virtual environment"
  python3 -m venv .venv
fi

log "Installing Python dependencies"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  log "Created .env from .env.example"
fi

mkdir -p data reports

cat <<'DONE'

Setup complete.

Run the radar with:
  bash run.sh

Optional: open .env and add a GitHub token for higher API limits.
DONE
