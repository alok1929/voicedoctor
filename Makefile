ROOT := $(shell pwd)

# Pipecat 0.0.98 pins numba==0.61.2, which supports Python <3.14 only.
PYTHON      := $(shell command -v python3.13 >/dev/null 2>&1 && echo python3.13 || echo python3)
CALLER_PY   := $(ROOT)/.venv/bin/python
BACKEND_PY  := $(ROOT)/evalra_backend/.venv/bin/python

MONGO_CONTAINER := evalra-mongo
MONGO_VOLUME    := evalra-mongo-data

.PHONY: start start-dev stop restart restart-dev all-stop all-restart start-backend-services \
        start-db start-caller start-backend start-frontend \
        stop-db stop-caller stop-backend stop-frontend \
        install install-backend install-frontend install-evals install-all \
        setup-tunnel start-tunnel stop-tunnel \
        setup-services start-services stop-services restart-services deploy-prod \
        start-frontend-dev stop-foreground \
        status help

# ── Helpers ───────────────────────────────────────────────────────────────────
# port-free PORT — succeeds (exits 0) when nothing is listening on PORT
port-free = ! nc -z localhost $(1) 2>/dev/null

# kill-port PORT — fuser first (lsof often misses next-server on this host)
define kill-port
	fuser -k $(1)/tcp 2>/dev/null || true; lsof -ti :$(1) 2>/dev/null | xargs -r kill -9 2>/dev/null || true
endef

# ── Installation ──────────────────────────────────────────────────────────────

install-evals:
	@echo "▶  Installing evals Python dependencies (root requirements.txt)"
	@if [ ! -d .venv ] || ! .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info < (3, 14) else 1)' 2>/dev/null; then \
		echo "   Creating Python venv in .venv ($(PYTHON))"; \
		rm -rf .venv; \
		$(PYTHON) -m venv .venv; \
	fi
	@.venv/bin/pip install -U pip
	@.venv/bin/pip install -r requirements.txt

install-backend:
	@echo "▶  Installing evalra_backend Python dependencies"
	@if [ ! -d evalra_backend/.venv ] || ! evalra_backend/.venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info < (3, 14) else 1)' 2>/dev/null; then \
		echo "   Creating Python venv in evalra_backend/.venv ($(PYTHON))"; \
		rm -rf evalra_backend/.venv; \
		$(PYTHON) -m venv evalra_backend/.venv; \
	fi
	@evalra_backend/.venv/bin/pip install -U pip
	@cd evalra_backend && .venv/bin/pip install -r requirements.txt

install-frontend:
	@echo "▶  Installing frontend npm dependencies"
	cd evals_frontend && npm install

install-all: install-evals install-backend install-frontend
	@echo "✅  All dependencies installed"

# ── Start everything ──────────────────────────────────────────────────────────

start: start-db
	@i=0; until nc -z localhost 27017 2>/dev/null; do \
		i=$$((i + 1)); \
		if [ $$i -ge 30 ]; then \
			echo "   MongoDB not accepting connections on :27017 after 30s"; \
			exit 1; \
		fi; \
		sleep 1; \
	done
	@sleep 1
	@$(MAKE) -j3 start-caller start-backend start-frontend

# Dev: same as start but frontend uses next dev (no build)
start-dev: start-db
	@i=0; until nc -z localhost 27017 2>/dev/null; do \
		i=$$((i + 1)); \
		if [ $$i -ge 30 ]; then \
			echo "   MongoDB not accepting connections on :27017 after 30s"; \
			exit 1; \
		fi; \
		sleep 1; \
	done
	@sleep 1
	@$(MAKE) -j3 start-caller start-backend start-frontend-dev

restart: stop start

restart-dev: stop start-dev

# Backend services only (DB + caller + evalra_backend, no frontend)
start-backend-services: start-db
	@i=0; until nc -z localhost 27017 2>/dev/null; do \
		i=$$((i + 1)); \
		if [ $$i -ge 30 ]; then \
			echo "   MongoDB not accepting connections on :27017 after 30s"; \
			exit 1; \
		fi; \
		sleep 1; \
	done
	@sleep 1
	@$(MAKE) -j2 start-caller start-backend

# ── Individual services ───────────────────────────────────────────────────────

start-db:
	@echo "▶  MongoDB"
	@if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^$(MONGO_CONTAINER)$$" \
		&& nc -z localhost 27017 2>/dev/null; then \
		echo "   already running"; \
	elif docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^$(MONGO_CONTAINER)$$"; then \
		docker start $(MONGO_CONTAINER) > /dev/null && echo "   restarted"; \
	else \
		docker volume create $(MONGO_VOLUME) > /dev/null 2>&1 || true; \
		docker run -d --name $(MONGO_CONTAINER) \
			-p 27017:27017 \
			--restart unless-stopped \
			-v $(MONGO_VOLUME):/data/db \
			mongo:latest > /dev/null && echo "   started"; \
	fi
	@if ! nc -z localhost 27017 2>/dev/null; then \
		i=0; \
		while [ $$i -lt 30 ]; do \
			nc -z localhost 27017 2>/dev/null && break; \
			i=$$((i + 1)); \
			sleep 1; \
		done; \
		if ! nc -z localhost 27017 2>/dev/null; then \
			echo "   ERROR: MongoDB container up but :27017 not accepting connections"; \
			echo "   Check: docker logs $(MONGO_CONTAINER)"; \
			exit 1; \
		fi; \
	fi

start-caller:
	@if nc -z localhost 7870 2>/dev/null; then \
		echo "▶  evals_caller_server  (:7870) — already running, skipping"; \
	else \
		echo "▶  evals_caller_server  (:7870)"; \
		$(CALLER_PY) main.py; \
	fi

start-backend:
	@if nc -z localhost 8100 2>/dev/null; then \
		echo "▶  evalra_backend       (:8100) — already running, skipping"; \
	else \
		echo "▶  evalra_backend       (:8100)"; \
		cd evalra_backend && $(BACKEND_PY) main.py; \
	fi

start-frontend:
	@if nc -z localhost 3000 2>/dev/null; then \
		echo "▶  evals_frontend       (:3000) — stopping existing"; \
		$(call kill-port,3000); \
		sleep 1; \
	fi
	@if nc -z localhost 3000 2>/dev/null; then \
		echo "▶  evals_frontend       (:3000) — still in use, skipping"; \
	else \
		echo "▶  evals_frontend       (:3000)"; \
		cd evals_frontend && npm run build && npm run start; \
	fi

# Dev-only: hot reload (do not use alongside systemd evalsera-frontend)
start-frontend-dev:
	@echo "▶  evals_frontend dev     (:3000, next dev)"
	@$(call kill-port,3000)
	cd evals_frontend && npm run dev

# ── Stop ──────────────────────────────────────────────────────────────────────

# all-stop: kill by port — catches any process on these ports, not just ones
# launched via this Makefile. Use this when the normal stop leaves orphans.
all-stop:
	@echo "◼  Killing anything on :7870 (caller)"
	@$(call kill-port,7870)
	@echo "◼  Killing anything on :8100 (backend)"
	@$(call kill-port,8100)
	@echo "◼  Killing anything on :3000 (frontend)"
	@$(call kill-port,3000)
	@echo "◼  MongoDB (stop only — data preserved)"
	@docker stop $(MONGO_CONTAINER) 2>/dev/null || true
	@echo "   done"

all-restart: all-stop
	@sleep 1
	@$(MAKE) start

stop: stop-caller stop-backend stop-frontend stop-db

stop-db:
	@echo "◼  MongoDB (stop only — data preserved)"
	@docker stop $(MONGO_CONTAINER) 2>/dev/null || true

stop-caller:
	@echo "◼  evals_caller_server"
	@pkill -f "$(ROOT)/main.py" 2>/dev/null || true

stop-backend:
	@echo "◼  evalra_backend"
	@pkill -f "$(ROOT)/evalra_backend/main.py" 2>/dev/null || true

stop-frontend:
	@echo "◼  evals_frontend"
	@$(call kill-port,3000)

# ── Cloudflare Tunnel ───────────────────────────────────────────────────────────

setup-tunnel:
	@./scripts/setup-cloudflare-tunnel.sh

start-tunnel:
	@sudo systemctl start evalsera-cloudflared.service 2>/dev/null \
		|| echo "Run 'make setup-tunnel' first (one-time Cloudflare auth)"

stop-tunnel:
	@sudo systemctl stop evalsera-cloudflared.service 2>/dev/null || true

# ── Production (systemd) ──────────────────────────────────────────────────────

setup-services:
	@./scripts/setup-systemd-services.sh

start-services:
	@sudo systemctl start evalsera.target

stop-services:
	@sudo systemctl stop evalsera-caller evalsera-backend evalsera-frontend

restart-services:
	@sudo systemctl restart evalsera-caller evalsera-backend evalsera-frontend

deploy-prod:
	@./scripts/deploy-prod.sh

stop-foreground:
	@./scripts/stop-foreground.sh

# ── Status ────────────────────────────────────────────────────────────────────

status:
	@echo "\n── Services ────────────────────────────────"
	@if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^$(MONGO_CONTAINER)$$" \
		&& nc -z localhost 27017 2>/dev/null; then \
		echo "  mongo    running  :27017"; \
	elif nc -z localhost 27017 2>/dev/null; then \
		echo "  mongo    running  :27017 (external)"; \
	else \
		echo "  mongo    not running"; \
	fi
	@curl -sf http://localhost:7870/health > /dev/null 2>&1 \
		&& echo "  caller   running  :7870" \
		|| echo "  caller   not running"
	@curl -sf http://localhost:8100/health > /dev/null 2>&1 \
		&& echo "  backend  running  :8100" \
		|| echo "  backend  not running"
	@curl -sf http://localhost:3000 > /dev/null 2>&1 \
		&& echo "  frontend running  :3000" \
		|| echo "  frontend not running"
	@echo ""

# ── Help ──────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "  make install-all             Install dependencies for backend, frontend, and root python (evals)"
	@echo "  make start                  Start everything (DB + caller + backend + frontend prod build)"
	@echo "  make start-dev              Start everything with next dev (no npm run build)"
	@echo "  make restart                Stop everything then start fresh"
	@echo "  make restart-dev            Stop everything then start-dev"
	@echo "  make start-backend-services Start DB + caller + evalra_backend only (no frontend)"
	@echo ""
	@echo "  make start-db               MongoDB Docker container"
	@echo "  make start-caller           evals_caller_server  :7870"
	@echo "  make start-backend          evalra_backend       :8100"
	@echo "  make start-frontend         evals_frontend       :3000"
	@echo ""
	@echo "  make all-stop               Force-kill by port (no skipping)"
	@echo "  make all-restart            all-stop then start fresh"
	@echo "  make stop                   Stop everything (by process name)"
	@echo "  make stop-db                Stop MongoDB container"
	@echo "  make stop-caller            Kill evals_caller_server"
	@echo "  make stop-backend           Kill evalra_backend"
	@echo "  make stop-frontend          Kill Next.js dev server"
	@echo ""
	@echo "  make status                 Health-check all four services"
	@echo ""
	@echo "  make setup-tunnel           One-time Cloudflare Tunnel + DNS (voicedoctor/evalsra-api.framewise.ai)"
	@echo "  make start-tunnel           Start tunnel systemd service"
	@echo "  make stop-tunnel            Stop tunnel systemd service"
	@echo ""
	@echo "  make setup-services         One-time systemd install (survives reboot; see prod.md)"
	@echo "  make start-services         Start caller + backend + frontend via systemd"
	@echo "  make stop-services          Stop systemd app services (tunnel/mongo unchanged)"
	@echo "  make restart-services       Restart systemd app services"
	@echo "  make deploy-prod            git pull, install, build frontend, restart services"
	@echo "  make stop-foreground        Kill make start processes without touching systemd"
	@echo "  make start-frontend-dev     Next.js dev server with hot reload"
	@echo ""
