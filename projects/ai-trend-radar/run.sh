#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="$ROOT/.venv/bin/python"
REPORT="$ROOT/reports/latest.html"

if [[ ! -x "$PYTHON" ]]; then
  echo "The virtual environment is missing. Run: bash setup.sh"
  exit 1
fi

"$PYTHON" "$ROOT/radar.py" "$@"

if [[ ! -f "$REPORT" ]]; then
  echo "The run finished, but no HTML report was created."
  exit 1
fi

printf '\nReport created: %s\n' "$REPORT"

if command -v wslview >/dev/null 2>&1; then
  nohup wslview "$REPORT" >/dev/null 2>&1 &
elif command -v explorer.exe >/dev/null 2>&1 && command -v wslpath >/dev/null 2>&1; then
  explorer.exe "$(wslpath -w "$REPORT")" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then
  nohup xdg-open "$REPORT" >/dev/null 2>&1 &
else
  echo "Open the report manually in your browser."
fi
