# ============================================================
# Ham Ninh AI — Developer Makefile
#
# Quick start:
#   make setup    # copy .env.example → .env
#   make up       # start all services, wait for health
#   make test     # verify health endpoints
#   make down     # stop services (keep volumes)
# ============================================================

BACKEND_URL ?= http://localhost:48721
HEALTH_TIMEOUT ?= 60
HEALTH_INTERVAL ?= 3

.PHONY: setup up down test logs restart clean status help

# Default target
help: ## Show available targets with descriptions
	@echo "Ham Ninh AI — Development Makefile"
	@echo ""
	@echo "Usage:"
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN { FS = ":.*##" }; { printf "  \033[36m%-10s\033[0m  %s\n", $$1, $$2 }'
	@echo ""

setup: ## Copy .env.example to .env if .env doesn't exist
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo ".env created from .env.example"; \
		echo "Edit .env and fill in real API keys before running:"; \
		echo "  - OPENAI_API_KEY (required for agent LLM & embeddings)"; \
		echo "  - GOOGLE_PLACES_API_KEY (required for places search)"; \
		echo "  - GOOGLE_ROUTES_API_KEY (required for routing)"; \
		echo "  - LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY (observability)"; \
	else \
		echo ".env already exists — skipping setup"; \
	fi

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

test: ## Run health check script against running services
	@echo "Running health checks..."
	./scripts/check-health.sh

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
