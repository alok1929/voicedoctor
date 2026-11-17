# Evalsera — production & operations

This guide covers running Evalsera on AWS (or any Linux host): **development** vs **production**, Cloudflare Tunnel, systemd, deploys, and routine ops.

## Architecture

| Component | Local port | Public URL |
|-----------|------------|------------|
| Next.js frontend | `:3000` | `https://voicedoctor.framewise.ai` |
| Caller (Vobiz / Pipecat) | `:7870` | `https://evalsra-api.framewise.ai` (default paths) |
| evalra backend | `:8100` | `https://evalsra-api.framewise.ai` (`/auth`, `/metrics`, `/reports`, `/pulses`) |
| MongoDB | `:27017` | Docker only (not exposed publicly) |
| Cloudflare Tunnel | — | Routes public hostnames → localhost |

Path routing lives in `cloudflared/config.yml`. Vobiz webhooks and WebSockets use the API hostname (`PUBLIC_HTTPS_URL` / `PUBLIC_WSS_URL` in root `.env`).

---

## Prerequisites (one-time on the server)

1. **OS packages**: Python 3.13, Node.js, npm, Docker, `cloudflared`, `make`, `git`.
2. **Clone & env**:
   ```bash
   cd /home/ubuntu/evalsera
   cp .env.example .env          # if present; fill API keys, Vobiz, PUBLIC_* URLs
   cp evals_frontend/.env.example evals_frontend/.env.local   # NEXT_PUBLIC_* → evalsra-api host
   cp evalra_backend/.env.example evalra_backend/.env
   ```
3. **Install dependencies**:
   ```bash
   make install-all
   ```
4. **Cloudflare Tunnel** (public HTTPS):
   ```bash
   make setup-tunnel    # one-time login + DNS CNAMEs
   make start-tunnel    # or: sudo systemctl start evalsera-cloudflared
   ```
5. **Production app services** (survive terminal close & reboot):
   ```bash
   make setup-services  # installs systemd units, builds frontend, enables on boot
   ```

After setup, four systemd units should be enabled:

- `evalsera-cloudflared.service` — tunnel
- `evalsera-caller.service` — `:7870`
- `evalsera-backend.service` — `:8100`
- `evalsera-frontend.service` — `:3000`

MongoDB runs in Docker with `--restart unless-stopped` (created by `make start-db`).

---

## Dev mode vs production

### Development (`make start-dev`)

Use when iterating locally on the EC2 box. Processes run in the **foreground** in your terminal; closing SSH kills them unless you use tmux/screen.

```bash
make start-dev                # Mongo + caller + backend + next dev (no build)
make start                    # same but frontend prod build + start (slow; rarely needed in dev)
make start-backend-services   # Mongo + caller + backend only
make start-frontend-dev       # Next.js hot reload only (npm run dev)
make status                   # quick health check
make stop-foreground          # stop dev processes only (safe if systemd is off)
make all-stop                 # force-kill anything on :7870/:8100/:3000 + stop Mongo
```

**Do not** run `make start-dev` while systemd production services are active — ports will conflict. Stop prod first:

```bash
make stop-services
make start-dev
```

Backend dev uses `evalra_backend/main.py` with **uvicorn reload**. Production systemd runs uvicorn **without** reload.

### Production (systemd)

Use for the live site. Services restart on failure and start on boot.

```bash
make status
make start-services           # start caller + backend + frontend
make stop-services            # stop app services (tunnel + Mongo unchanged)
make restart-services         # restart after config-only changes
make deploy-prod              # full deploy (see below)
```

**Logs:**

```bash
journalctl -u evalsera-caller -f
journalctl -u evalsera-backend -f
journalctl -u evalsera-frontend -f
journalctl -u evalsera-cloudflared -f
```

**Service status:**

```bash
sudo systemctl status evalsera-caller evalsera-backend evalsera-frontend evalsera-cloudflared
```

---

## Deploy to production

After merging changes to the branch you deploy from (e.g. `main`):

```bash
cd /home/ubuntu/evalsera
make deploy-prod
```

This runs `scripts/deploy-prod.sh`:

1. `git pull`
2. `make install-all` (Python + npm deps)
3. `npm run build` in `evals_frontend`
4. `sudo systemctl restart evalsera-caller evalsera-backend evalsera-frontend`
5. `make status`

### Manual deploy steps

If you prefer step-by-step:

```bash
git pull
make install-all
cd evals_frontend && npm run build
sudo systemctl restart evalsera-caller evalsera-backend evalsera-frontend
make status
curl -sf https://evalsra-api.framewise.ai/health
curl -sfI https://voicedoctor.framewise.ai | head -1
```

### When to rebuild vs restart only

| Change | Action |
|--------|--------|
| Frontend UI / Next.js code | `npm run build` + restart `evalsera-frontend` (included in `deploy-prod`) |
| Caller Python code | restart `evalsera-caller` |
| Backend Python code | restart `evalsera-backend` |
| Root `.env` or backend `.env` | restart affected service(s) |
| `evals_frontend/.env.local` | rebuild frontend + restart frontend |
| Cloudflare config | `sudo systemctl restart evalsera-cloudflared` |

---

## Pulse cron (scheduled evals)

Recurring pulses are driven by `evalra_backend/pulse_runner.py`. Add a **system crontab** entry (runs every minute):

```bash
crontab -e
```

```cron
* * * * * cd /home/ubuntu/evalsera/evalra_backend && .venv/bin/python pulse_runner.py >> /home/ubuntu/evalsera/evalra_backend/pulse_runner.log 2>&1
```

Ensure caller + backend + Mongo are up (systemd handles that in prod).

---

## MongoDB

```bash
make start-db                 # create/start container (persistent volume evalra-mongo-data)
make stop-db                  # stop container; data preserved
docker logs evalra-mongo      # troubleshoot
```

If `:27017` refuses connections after a full disk event, check `docker logs evalra-mongo` and recreate only if the volume is corrupt (last resort).

---

## Cloudflare Tunnel

```bash
make setup-tunnel             # one-time
make start-tunnel
make stop-tunnel
```

Config: `cloudflared/config.yml`. Credentials: `~/.cloudflared/` or `.cloudflare-tunnel-token` at repo root (see setup script).

Public hostnames (typical):

- `voicedoctor.framewise.ai` → `http://localhost:3000`
- `evalsra-api.framewise.ai` → path-split to `:7870` / `:8100`

---

## Environment variables (checklist)

| File | Purpose |
|------|---------|
| `.env` | Vobiz, OpenAI, Deepgram, `PUBLIC_HTTPS_URL`, `PUBLIC_WSS_URL`, caller settings |
| `evals_frontend/.env.local` | `NEXT_PUBLIC_*` API URLs (must match tunnel hostname) |
| `evalra_backend/.env` | Mongo URI, JWT/auth, backend secrets |

After changing `PUBLIC_*` or `NEXT_PUBLIC_*`, restart caller and rebuild/restart frontend.

---

## Troubleshooting

| Symptom | Likely fix |
|---------|------------|
| Port already in use | `make status`; prod: `make stop-services`; dev: `make stop-foreground` or `make all-stop` |
| Unstyled frontend | Orphan `next dev` vs prod build — `make stop-services`, `cd evals_frontend && npm run build`, restart frontend |
| `make all-stop` killed prod | Expected — it kills by port. Use `make stop-services` in prod instead |
| Tunnel 502 / connection refused | App not listening — `make status`, check `journalctl` |
| Mongo connection refused | `make start-db`, wait for `:27017`, check disk space |
| Python / numba errors | Use Python 3.13 venv (`make install-evals` recreates if 3.14) |

**Health checks:**

```bash
curl http://localhost:7870/health
curl http://localhost:8100/health
curl http://localhost:3000
curl https://evalsra-api.framewise.ai/health
```

---

## Quick reference

```bash
# First-time prod setup
make install-all && make setup-tunnel && make setup-services

# Daily dev on server
make stop-services && make start-dev

# Ship to prod
make deploy-prod

# Reboot survival (should auto-start if enabled)
sudo systemctl enable evalsera-cloudflared evalsera.target
```

Unit templates: `systemd/*.service` (paths substituted by `scripts/setup-systemd-services.sh`).


### Quick cheat sheet
| Goal                       | Command                                                     |
|----------------------------|-------------------------------------------------------------|
| First-time prod            | `make setup-tunnel` → `make setup-services`                 |
| Check status               | `make status`                                               |
| Dev on server              | `make stop-services` → `make start-dev`                     |
| Back to prod after dev     | `make deploy-prod` (or `make stop-foreground` + `make start-services`) |
| Deploy code change         | `make deploy-prod`                                          |
| Prod logs (live tail)      | `journalctl -u evalsera-caller -f` (or `-u evalsera-backend` / `-u evalsera-frontend`) |
| Reboot survival            | Already handled — no extra enable needed                    |
