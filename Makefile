# Dev helpers. Docker is for production; local `python main.py` is for iteration.
.DEFAULT_GOAL := help
VENV := ./venv/bin

.PHONY: help dev run install prod logs stop

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-9s\033[0m %s\n", $$1, $$2}'

dev: ## Run locally with hot-reload (edit a .py file -> auto-restart)
	@docker compose up -d pot-provider
	@docker compose stop bot 2>/dev/null || true
	@echo ">> Prod bot stopped (same token can't run twice). Local bot with hot-reload:"
	$(VENV)/watchmedo auto-restart --directory=. --pattern="*.py" --recursive --ignore-patterns="*/venv/*" -- $(VENV)/python main.py

run: ## Run locally once (no hot-reload)
	@docker compose up -d pot-provider
	@docker compose stop bot 2>/dev/null || true
	$(VENV)/python main.py

install: ## Install runtime + dev deps into ./venv
	$(VENV)/pip install -r requirements.txt -r requirements-dev.txt

prod: ## Build & (re)start the full production stack in Docker
	docker compose up -d --build

logs: ## Tail the production bot logs
	docker compose logs -f bot

stop: ## Stop the whole production stack
	docker compose down
