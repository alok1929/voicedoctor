#!/usr/bin/env bash
# Pull latest code, install deps, rebuild frontend, restart systemd services.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "▶  git pull"
git pull

echo "▶  install dependencies"
make install-all

echo "▶  build frontend"
(cd evals_frontend && npm run build)

echo "▶  restart services"
sudo systemctl restart evalsera-caller evalsera-backend evalsera-frontend

echo ""
echo "✅  Deploy complete."
make -C "$ROOT" status
