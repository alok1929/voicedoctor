#!/usr/bin/env bash
# Install systemd units so Evalsera survives terminal close and reboots.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="$ROOT/systemd"

echo "▶  Evalsera systemd setup (repo: $ROOT)"
echo ""

if pgrep -f "$ROOT/main.py" >/dev/null 2>&1 \
	|| pgrep -f "$ROOT/evalra_backend" >/dev/null 2>&1 \
	|| nc -z localhost 7870 2>/dev/null \
	|| nc -z localhost 8100 2>/dev/null \
	|| nc -z localhost 3000 2>/dev/null; then
	echo "Stopping foreground dev processes on :7870 / :8100 / :3000 ..."
	"$ROOT"/scripts/stop-foreground.sh 2>/dev/null || make -C "$ROOT" all-stop || true
	sleep 1
fi

echo "▶  Ensuring MongoDB container exists ..."
make -C "$ROOT" start-db

if [[ ! -x "$ROOT/.venv/bin/python" ]] || [[ ! -x "$ROOT/evalra_backend/.venv/bin/python" ]]; then
	echo "▶  Installing Python dependencies ..."
	make -C "$ROOT" install-evals install-backend
fi

if [[ ! -d "$ROOT/evals_frontend/node_modules" ]]; then
	echo "▶  Installing frontend dependencies ..."
	make -C "$ROOT" install-frontend
fi

echo "▶  Building frontend (production) ..."
cd "$ROOT/evals_frontend" && npm run build

echo "▶  Installing systemd units ..."
for unit in evalsera-caller.service evalsera-backend.service evalsera-frontend.service evalsera.target; do
	src="$UNIT_DIR/$unit"
	if [[ ! -f "$src" ]]; then
		echo "Missing $src" >&2
		exit 1
	fi
	sed "s|@REPO_ROOT@|$ROOT|g" "$src" | sudo tee "/etc/systemd/system/$unit" > /dev/null
done

sudo systemctl daemon-reload
sudo systemctl enable evalsera.target evalsera-caller evalsera-backend evalsera-frontend
sudo systemctl restart evalsera-caller evalsera-backend evalsera-frontend

echo ""
echo "✅  Production services enabled and started."
echo ""
echo "  sudo systemctl status evalsera-caller evalsera-backend evalsera-frontend"
echo "  journalctl -u evalsera-caller -f"
echo ""
echo "See prod.md for deploy workflow and dev vs prod modes."
