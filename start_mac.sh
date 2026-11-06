#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "Starting UniPowerGuard (macOS / Linux) on http://127.0.0.1:8095 ..."
if command -v open >/dev/null 2>&1; then
  (sleep 1 && open "http://127.0.0.1:8095") &
fi
python3 server.py
