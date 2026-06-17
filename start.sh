#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

DEFAULT_HOST="${HOST:-127.0.0.1}"
DEFAULT_PORT="${PORT:-8080}"

read -r -p "Clean cache and unnecessary posters? [y/N]: " CLEAN_INPUT
read -r -p "IP/host [${DEFAULT_HOST}]: " HOST_INPUT
read -r -p "Port [${DEFAULT_PORT}]: " PORT_INPUT

HOST="${HOST_INPUT:-$DEFAULT_HOST}"
PORT="${PORT_INPUT:-$DEFAULT_PORT}"

if [[ ! -x ".venv/bin/python" ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv sync --locked
  else
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
  fi
fi

if [[ "${CLEAN_INPUT:-}" =~ ^[Yy]$ ]]; then
  echo "Cleaning cache and posters/..."
  .venv/bin/python tools/cleanup_runtime.py
fi

mkdir -p webapp/.cache/matplotlib webapp/.cache/xdg

export MPLCONFIGDIR="$PWD/webapp/.cache/matplotlib"
export XDG_CACHE_HOME="$PWD/webapp/.cache/xdg"
export MPLBACKEND="Agg"

echo "MapToPoster is starting..."
echo "Open http://${HOST}:${PORT}"

exec .venv/bin/python webapp/app.py "$HOST" "$PORT"
