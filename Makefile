.PHONY: setup dev lint types test test-backend test-frontend migrate prod help

PYTHON := python3.13
VENV   := backend/.venv
PIP    := $(VENV)/bin/pip

help: ## Zeige alle verfügbaren Targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: ## Einmalige Initialisierung: venv, npm install, pre-commit hooks
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e "backend/[dev]"
	cd frontend && npm install
	$(VENV)/bin/pre-commit install
	mkdir -p infrastructure/secrets data
	@echo ""
	@echo "Setup abgeschlossen!"
	@echo "  1. Kopiere .env.example nach .env"
	@echo "  2. Anthropic-Key hinterlegen: echo 'sk-ant-...' > infrastructure/secrets/anthropic_key.txt"
	@echo "  3. Ollama-Modelle laden: ollama pull mistral-nemo:12b && ollama pull nomic-embed-text"
	@echo "  4. Starten mit: make dev"

dev: ## Backend-Container + Vite Dev-Server starten
	docker compose -f infrastructure/docker-compose.dev.yml up -d backend
	cd frontend && npm run dev

lint: ## ruff check + format (Backend) + ESLint (Frontend)
	cd backend && .venv/bin/ruff check .
	cd backend && .venv/bin/ruff format --check .
	cd frontend && npm run lint

types: ## Frontend-Typen aus OpenAPI-Schema neu generieren
	cd backend && ../.venv/bin/python ../scripts/generate_schema.py \
	  --output ../docs/api/openapi.json
	cd frontend && npx openapi-typescript ../docs/api/openapi.json \
	  --output src/types/api.ts
	@echo "Typen neu generiert. docs/api/openapi.json committen falls geändert."

test: test-backend test-frontend ## Alle Tests

test-backend: ## Nur pytest
	cd backend && .venv/bin/pytest tests/ -v --tb=short

test-frontend: ## Nur Vitest
	cd frontend && npx vitest run

migrate: ## DB-Migrationen ausführen
	$(VENV)/bin/python scripts/migrate.py upgrade

prod: ## Produktionsdeployment
	docker compose -f infrastructure/docker-compose.prod.yml up -d

# ─── Ollama ──────────────────────────────────────────────────────────────────

.PHONY: ollama-setup
ollama-setup: ## Ollama installieren/prüfen und Modelle herunterladen
	@bash scripts/setup_ollama.sh
