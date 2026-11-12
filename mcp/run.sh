#!/usr/bin/env bash
# Start the MCP without Docker (Linux / macOS). Reads ./.env if present.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && { set -a; . ./.env; set +a; }
: "${CONNECTION_JSON:?Set CONNECTION_JSON (copy .env.example to .env and fill it in)}"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
exec .venv/bin/python server.py
