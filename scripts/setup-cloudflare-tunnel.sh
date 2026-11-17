#!/usr/bin/env bash
# One-time Cloudflare Tunnel setup for evalsera on AWS.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CF_DIR="$HOME/.cloudflared"
CONFIG="$ROOT/cloudflared/config.yml"
TUNNEL_NAME="evalsera-aws"
FRONTEND_HOST="voicedoctor.framewise.ai"
API_HOST="evalsra-api.framewise.ai"
TOKEN_FILE="$ROOT/.cloudflare-tunnel-token"

mkdir -p "$CF_DIR"

if [[ -f "$TOKEN_FILE" ]]; then
  # Dashboard token flow (Zero Trust → Tunnels → install command).
  TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
  echo "Using tunnel token from $TOKEN_FILE"
  sudo tee /etc/systemd/system/evalsera-cloudflared.service > /dev/null <<EOF
[Unit]
Description=Cloudflare Tunnel (evalsera)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=$ROOT
ExecStart=/usr/bin/cloudflared tunnel --config $CONFIG run --token ${TOKEN}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable --now evalsera-cloudflared.service
  echo "Tunnel service started (token mode)."
  echo "Configure public hostnames in Cloudflare Zero Trust if not already done:"
  echo "  $FRONTEND_HOST → http://localhost:3000"
  echo "  $API_HOST       → path routes (see cloudflared/config.yml)"
  exit 0
fi

if [[ ! -f "$CF_DIR/cert.pem" ]]; then
  echo ""
  echo "Step 1 — Authenticate (open the URL below in your browser, pick framewise.ai):"
  echo ""
  cloudflared tunnel login
fi

if ! cloudflared tunnel list 2>/dev/null | grep -qw "$TUNNEL_NAME"; then
  echo "Creating tunnel: $TUNNEL_NAME"
  cloudflared tunnel create "$TUNNEL_NAME"
fi

TUNNEL_ID="$(cloudflared tunnel list -o json | python3 -c "
import json, sys
name = '$TUNNEL_NAME'
for t in json.load(sys.stdin):
    if t.get('name') == name:
        print(t['id'])
        break
else:
    raise SystemExit('tunnel not found: ' + name)
")"

echo "Tunnel ID: $TUNNEL_ID"

cloudflared tunnel route dns "$TUNNEL_NAME" "$FRONTEND_HOST" || true
cloudflared tunnel route dns "$TUNNEL_NAME" "$API_HOST" || true

# Prepend tunnel identity to ingress config.
TMP="$(mktemp)"
{
  echo "tunnel: $TUNNEL_ID"
  echo "credentials-file: $CF_DIR/$TUNNEL_ID.json"
  echo ""
  sed -n '/^ingress:/,$p' "$CONFIG"
} > "$TMP"
mv "$TMP" "$CONFIG"

sudo tee /etc/systemd/system/evalsera-cloudflared.service > /dev/null <<EOF
[Unit]
Description=Cloudflare Tunnel (evalsera)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=$ROOT
ExecStart=/usr/bin/cloudflared tunnel --config $CONFIG run
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now evalsera-cloudflared.service

echo ""
echo "Done. DNS routes:"
echo "  https://$FRONTEND_HOST  → localhost:3000"
echo "  https://$API_HOST       → localhost:8100 / :7870 (by path)"
echo ""
echo "Test: curl https://$API_HOST/health"
