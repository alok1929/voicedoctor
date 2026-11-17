#!/usr/bin/env bash
# Stop processes started via 'make start' (foreground dev), not systemd units.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

for unit in evalsera-caller evalsera-backend evalsera-frontend; do
	if systemctl is-active --quiet "$unit" 2>/dev/null; then
		echo "Production systemd services are running."
		echo "Use: make stop-services   (not stop-foreground / all-stop)"
		exit 1
	fi
done

fuser -k 7870/tcp 2>/dev/null || true
fuser -k 8100/tcp 2>/dev/null || true
fuser -k 3000/tcp 2>/dev/null || true

pkill -f "$ROOT/evalra_backend/main.py" 2>/dev/null || true
pkill -f "$ROOT/main.py" 2>/dev/null || true

echo "Foreground processes on :7870 :8100 :3000 stopped (systemd units untouched)."
