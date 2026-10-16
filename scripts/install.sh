#!/bin/bash
# Install cutthebullshit into its own Python environment and check the machine.
#
#   scripts/install.sh               -> .venv in the repo, then `cutthebullshit doctor`
#   VENV=~/envs/ctb scripts/install.sh
#   PYTHON=/opt/homebrew/bin/python3.12 scripts/install.sh
#
# Needs Python 3.11 or newer (with uv installed, it finds or downloads one). Uses uv when it is installed, pip otherwise.
# Afterwards run it as  .venv/bin/cutthebullshit ...  or put .venv/bin on your PATH.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
venv="${VENV:-$repo/.venv}"

ok_python() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; }

py="${PYTHON:-}"
if [ -z "$py" ]; then
  for c in python3.13 python3.12 python3.11 python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if command -v "$c" >/dev/null 2>&1 && ok_python "$c"; then py="$c"; break; fi
  done
fi
if [ -z "$py" ] && command -v uv >/dev/null 2>&1; then
  py="$(uv python find '>=3.11' 2>/dev/null || true)"
  [ -n "$py" ] || { uv python install 3.12 && py="$(uv python find '>=3.11')"; }
fi
if [ -z "$py" ] || ! ok_python "$py"; then
  echo "Python 3.11+ not found. Install one (e.g. brew install python@3.12 or uv python install 3.12) and rerun," >&2
  echo "or point PYTHON at it: PYTHON=/path/to/python3.12 $0" >&2
  exit 1
fi
echo "python: $py ($("$py" -c 'import sys; print(sys.version.split()[0])'))"
echo "environment: $venv"

if command -v uv >/dev/null 2>&1; then
  [ -x "$venv/bin/python" ] || uv venv --python "$py" "$venv"
  uv pip install --python "$venv/bin/python" -e "$repo${EXTRAS:+[$EXTRAS]}"
else
  [ -x "$venv/bin/python" ] || "$py" -m venv "$venv"
  "$venv/bin/python" -m pip install --upgrade pip
  "$venv/bin/python" -m pip install -e "$repo${EXTRAS:+[$EXTRAS]}"
fi

echo
"$venv/bin/cutthebullshit" doctor || true
echo
echo "installed: $venv/bin/cutthebullshit"
echo "settings:  copy $repo/cutthebullshit.example.toml to ~/.cutthebullshit/config.toml (or pass --config) and edit it"
