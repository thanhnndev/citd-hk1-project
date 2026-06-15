# ============================================================
# Ham Ninh AI — Developer Makefile
#
# Quick start:
#   make setup    # copy .env.example → .env
#   make up       # start all services, wait for health
#   make test     # run all unit + integration tests
#   make down     # stop services (keep volumes)
# ============================================================

BACKEND_URL ?= http://localhost:48721
HEALTH_TIMEOUT ?= 60
HEALTH_INTERVAL ?= 3
PYTHON ?= python
PYTEST_FLAGS ?= -v --tb=short

# PYTHONPATH must include root (for agents.*) and backend (for app.*)
export PYTHONPATH := .:backend

.PHONY: setup up down test test-all test-backend test-agents \
        test-unit test-integration verify-runtime logs restart clean status help \
        install install-backend install-agents lint format infra-test \
        seed seed-admin seed-user

# ── Default target ──────────────────────────────────────────
help: ## Show available targets with descriptions
	@echo "Ham Ninh AI — Development Makefile"
	@echo ""
	@echo "Usage:"
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN { FS = ":.*##" }; { printf "  \033[36m%-18s\033[0m  %s\n", $$1, $$2 }'
	@echo ""

# ── Environment ─────────────────────────────────────────────
setup: ## Copy .env.example to .env if .env doesn't exist
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo ".env created from .env.example"; \
		echo "Edit .env and fill in real API keys before running:"; \
		echo "  - OPENAI_API_KEY (required for agent LLM & embeddings)"; \
		echo "  - GOONG_API_KEY (required for places search)"; \
		echo "  - GOONG_API_KEY (required for routing)"; \
		echo "  - LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY (observability)"; \
	else \
		echo ".env already exists — skipping setup"; \
	fi

# ── Infrastructure ──────────────────────────────────────────
up: ## Start all services and wait for backend /health/ready
	@if [ ! -f .env ]; then \
		echo "ERROR: .env not found. Run \`make setup\` first."; \
		exit 1; \
	fi
	@echo "Starting services..."
	docker compose up -d --build
	@echo ""
	@echo "Waiting for backend to be ready at $(BACKEND_URL)/health/ready ..."
	@elapsed=0; \
	while [ $$elapsed -lt $(HEALTH_TIMEOUT) ]; do \
		response=$$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$(BACKEND_URL)/health/ready" 2>/dev/null || echo "000"); \
		if [ "$$response" = "200" ]; then \
			echo "Backend is ready after $${elapsed}s!"; \
			echo "Visit: $(BACKEND_URL)/docs"; \
			exit 0; \
		fi; \
		echo "  Waiting... ($${elapsed}s / $(HEALTH_TIMEOUT)s) — status: $$response"; \
		sleep $(HEALTH_INTERVAL); \
		elapsed=$$((elapsed + $(HEALTH_INTERVAL))); \
	done; \
	echo "ERROR: Backend did not become ready within $(HEALTH_TIMEOUT)s"; \
	echo "Tips:"; \
	echo "  - Run \`make logs\` to see backend output"; \
	echo "  - Run \`make status\` to check service state"; \
	exit 1

down: ## Stop all services (keeps volumes)
	@echo "Stopping services..."
	docker compose down
	@echo "Services stopped."

logs: ## Tail backend service logs
	docker compose logs -f backend

restart: ## Restart the backend service
	@echo "Restarting backend..."
	docker compose restart backend
	@echo "Backend restarted."

clean: ## Stop all services and remove volumes (DATA LOSS WARNING)
	@echo "WARNING: This will remove all containers and volumes. Data will be lost."
	@echo "Removing containers and volumes..."
	docker compose down -v
	@echo "Clean complete."

status: ## Show running services and their health state
	@echo "Service status:"
	docker compose ps

infra-test: ## Run HTTP health checks against running services
	@echo "Running health checks..."
	./scripts/check-health.sh

seed: ## Create or update development admin and user accounts
	docker compose --profile tools run --rm seed-users

seed-admin: ## Create or update only the development admin account
	docker compose --profile tools run --rm seed-users --only admin

seed-user: ## Create or update only the development user account
	docker compose --profile tools run --rm seed-users --only user

# ── Dependencies ────────────────────────────────────────────
install-backend: ## Install backend Python dependencies
	$(PYTHON) -m pip install -r backend/requirements.txt

install-agents: ## Install agents Python dependencies
	$(PYTHON) -m pip install -r agents/requirements.txt

install: install-backend install-agents ## Install all Python dependencies

# ── Testing ─────────────────────────────────────────────────
test-backend: ## Run backend unit tests (excludes @integration, PYTHONPATH=. backend)
	@echo "Running backend tests..."
	$(PYTHON) -m pytest backend/tests/ -m "not integration" $(PYTEST_FLAGS)

test-agents: ## Run agents module tests
	@echo "Running agents tests..."
	$(PYTHON) -m pytest agents/ $(PYTEST_FLAGS)

test-unit: test-backend test-agents ## Run all unit tests (offline, no infra)

test-integration: ## Run integration tests (requires live services)
	@echo "Running integration tests..."
	$(PYTHON) -m pytest backend/tests/ -m integration $(PYTEST_FLAGS)

verify-runtime: ## Run full runtime verification suite (integration + operational + UAT)
	@echo "Running runtime verification suite..."
	$(PYTHON) scripts/integration_test.py --base-url $(BACKEND_URL)

test-all: test-unit infra-test ## Run unit tests + infra health checks

# Alias: "make test" runs everything (unit + infra)
test: test-all ## Run all tests (unit + health checks)

# ── Lint & Format ──────────────────────────────────────────
lint: ## Lint Python code (ruff or flake8 if available)
	@echo "Linting Python code..."
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check backend/ agents/ scripts/; \
	else \
		echo "ruff not installed — install with: pip install ruff"; \
		exit 1; \
	fi

format: ## Format Python code (ruff or black if available)
	@echo "Formatting Python code..."
	@if command -v ruff >/dev/null 2>&1; then \
		ruff format backend/ agents/ scripts/; \
	else \
		echo "ruff not installed — install with: pip install ruff"; \
		exit 1; \
	fi
