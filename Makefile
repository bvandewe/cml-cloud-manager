.PHONY: help build-ui dev-ui run test lint docs-lint format clean install-dev-tools update-neuroglia-config restart-service

# Default target
.DEFAULT_GOAL := help

# ==============================================================================
# VARIABLES
# ==============================================================================

# Load environment variables from .env file
ifneq (,$(wildcard ./.env))
    include .env
    export
endif

# Docker settings (Standalone mode - includes all infrastructure)
COMPOSE_FILE := docker-compose.yml
COMPOSE := docker-compose -f $(COMPOSE_FILE)

# Docker settings (Shared mode - connects to aix_aix-net from AIX)
SHARED_COMPOSE_FILE := docker-compose.shared.yml
SHARED_ENV_FILE := .env-shared
SHARED_COMPOSE := docker-compose -f $(SHARED_COMPOSE_FILE) --env-file $(SHARED_ENV_FILE)

# Production Docker settings
PROD_COMPOSE_FILE := deployment/docker-compose/docker-compose.prod.yml
PROD_ENV_FILE := deployment/docker-compose/.env.prod

# Base command
PROD_COMPOSE_CMD := docker-compose -f $(PROD_COMPOSE_FILE) --env-file $(PROD_ENV_FILE)

# Add local overrides if they exist
ifneq (,$(wildcard deployment/docker-compose/docker-compose.prod.local.yml))
    PROD_COMPOSE_CMD += -f deployment/docker-compose/docker-compose.prod.local.yml
endif
ifneq (,$(wildcard deployment/docker-compose/.env.prod.local))
    PROD_COMPOSE_CMD += --env-file deployment/docker-compose/.env.prod.local
endif

PROD_COMPOSE := $(PROD_COMPOSE_CMD)

# Microservice directories
CONTROL_PLANE_DIR := src/control-plane-api
RESOURCE_SCHEDULER_DIR := src/resource-scheduler
LABLET_CONTROLLER_DIR := src/lablet-controller
WORKER_CONTROLLER_DIR := src/worker-controller
SCENARIO_ENGINE_DIR := src/scenario-engine

# Port settings with defaults (can be overridden in .env)
APP_PORT ?= 8020
RESOURCE_SCHEDULER_PORT ?= 8081
LABLET_CONTROLLER_PORT ?= 8082
WORKER_CONTROLLER_PORT ?= 8083
SCENARIO_ENGINE_PORT ?= 8084
KEYCLOAK_PORT ?= 8021
MONGODB_PORT ?= 8022
MONGODB_EXPRESS_PORT ?= 8023
EVENT_PLAYER_PORT ?= 8024
ETCD_PORT ?= 2379
OTEL_COLLECTOR_PORT_GRPC ?= 4317
OTEL_COLLECTOR_PORT_HTTP ?= 4318

# Application settings
APP_SERVICE_NAME := control-plane-api
APP_URL := http://localhost:$(APP_PORT)
API_DOCS_URL := $(APP_URL)/api/docs

# Infrastructure settings
MONGO_URL := mongodb://localhost:$(MONGODB_PORT)
MONGO_EXPRESS_URL := http://localhost:$(MONGODB_EXPRESS_PORT)
KEYCLOAK_URL := http://localhost:$(KEYCLOAK_PORT)
EVENT_PLAYER_URL := http://localhost:$(EVENT_PLAYER_PORT)
ETCD_URL := http://localhost:$(ETCD_PORT)

# Observability settings
OTEL_GRPC_URL := localhost:$(OTEL_COLLECTOR_PORT_GRPC)
OTEL_HTTP_URL := localhost:$(OTEL_COLLECTOR_PORT_HTTP)

# Documentation settings
DOCS_SITE_NAME ?= "Cml Cloud Manager"
DOCS_SITE_URL ?= "https://bvandewe.github.io/lablet-cloud-manager"
DOCS_FOLDER ?= ./docs
DOCS_DEV_PORT ?= 8000

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

# ==============================================================================
# HELP
# ==============================================================================

##@ General

help: ## Display this help message
	@echo "$(BLUE)Lablet Cloud Manager - Multi-Service Development Commands$(NC)"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"; printf "Usage:\n  make $(GREEN)<target>$(NC)\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  $(GREEN)%-25s$(NC) %s\n", $$1, $$2 } /^##@/ { printf "\n$(YELLOW)%s$(NC)\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

# ==============================================================================
# DOCKER COMMANDS
# ==============================================================================

##@ Docker

build: ## Build Docker images for all services
	@echo "$(BLUE)Building Docker images...$(NC)"
	$(COMPOSE) build

up: ## Start services in the background
	@echo "$(BLUE)Starting Docker services...$(NC)"
	$(COMPOSE) up -d
	@echo "$(GREEN)Services started!$(NC)"
	@$(MAKE) urls

down: ## Stop and remove services
	@echo "$(BLUE)Stopping Docker services...$(NC)"
	$(COMPOSE) down
	@echo "$(GREEN)Services stopped!$(NC)"

start: ## Start existing containers
	@echo "$(BLUE)Starting Docker containers...$(NC)"
	$(COMPOSE) start
	@echo "$(GREEN)Containers started!$(NC)"

stop: ## Stop running containers
	@echo "$(BLUE)Stopping Docker containers...$(NC)"
	$(COMPOSE) stop
	@echo "$(GREEN)Containers stopped!$(NC)"

restart: ## Restart all services (with refreshed environment variables)
	@echo "$(BLUE)Restarting Docker services...$(NC)"
	$(COMPOSE) up -d --force-recreate
	@echo "$(GREEN)Services restarted with refreshed environment variables!$(NC)"

restart-service: ## Restart a single Docker service (usage: make restart-service SERVICE=service_name)
	@if [ -z "$(SERVICE)" ]; then \
		echo "$(RED)Please specify SERVICE=<service_name>$(NC)"; \
		echo "Available services:"; \
		$(COMPOSE) config --services; \
		exit 1; \
	fi
	@echo "$(BLUE)Restarting Docker service '$(SERVICE)'...$(NC)"
	$(COMPOSE) up -d --force-recreate $(SERVICE)
	@echo "$(GREEN)Service '$(SERVICE)' restarted with refreshed environment variables.$(NC)"

rebuild-service: ## Rebuild a single service without cache and restart (usage: make rebuild-service SERVICE=service_name)
	@if [ -z "$(SERVICE)" ]; then \
		echo "$(RED)Please specify SERVICE=<service_name>$(NC)"; \
		echo "Available services:"; \
		$(COMPOSE) config --services; \
		exit 1; \
	fi
	@echo "$(BLUE)Rebuilding $(SERVICE) without cache...$(NC)"
	$(COMPOSE) build --no-cache $(SERVICE)
	@echo "$(BLUE)Restarting $(SERVICE)...$(NC)"
	$(COMPOSE) up -d --force-recreate $(SERVICE)
	@echo "$(GREEN)$(SERVICE) rebuilt and restarted!$(NC)"

dev: ## Build and start services with live logs
	@echo "$(BLUE)Starting development environment...$(NC)"
	$(COMPOSE) up --build

rebuild: ## Rebuild services from scratch without cache
	@echo "$(BLUE)Rebuilding services from scratch...$(NC)"
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d --force-recreate
	@echo "$(GREEN)Rebuild complete!$(NC)"

rebuild-services: ## Rebuild all microservices (control-plane-api, resource-scheduler, lablet-controller, worker-controller, scenario-engine)
	@echo "$(BLUE)Rebuilding all microservices...$(NC)"
	$(COMPOSE) build --no-cache control-plane-api resource-scheduler lablet-controller worker-controller scenario-engine
	@echo "$(BLUE)Restarting microservices...$(NC)"
	$(COMPOSE) up -d --force-recreate control-plane-api resource-scheduler lablet-controller worker-controller scenario-engine
	@echo "$(GREEN)All microservices rebuilt and restarted!$(NC)"
	@$(MAKE) urls

logs: ## Show logs from all services
	$(COMPOSE) logs -f

logs-api: ## Show logs from the control-plane-api service
	$(COMPOSE) logs -f control-plane-api

logs-resource-scheduler: ## Show logs from the resource-scheduler service
	$(COMPOSE) logs -f resource-scheduler

logs-lablet-controller: ## Show logs from the lablet-controller service
	$(COMPOSE) logs -f lablet-controller

logs-worker-controller: ## Show logs from the worker-controller service
	$(COMPOSE) logs -f worker-controller

logs-scenario-engine: ## Show logs from the scenario-engine service
	$(COMPOSE) logs -f scenario-engine

logs-worker: ## Show logs from the legacy worker service
	$(COMPOSE) logs -f worker

logs-etcd: ## Show logs from the etcd service
	$(COMPOSE) logs -f etcd

ps: ## Show running containers
	$(COMPOSE) ps

docker-clean: ## Stop services and remove all volumes (WARNING: removes all data)
	@echo "$(RED)WARNING: This will remove all containers, volumes, and data!$(NC)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		$(COMPOSE) down -v; \
		echo "$(GREEN)Cleanup complete!$(NC)"; \
	else \
		echo "$(YELLOW)Cleanup cancelled.$(NC)"; \
	fi

redis-flush: ## Flush all Redis data (clears sessions, forces re-login)
	@echo "$(YELLOW)Flushing Redis...$(NC)"
	$(COMPOSE) exec redis redis-cli FLUSHALL
	@echo "$(GREEN)Redis flushed!$(NC)"

reset-mongodb: ## Reset MongoDB (clears all data, recreates volume)
	@echo "$(RED)WARNING: This will delete all MongoDB data!$(NC)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		$(COMPOSE) down mongodb mongo-express; \
		docker volume rm lablet-cloud-manager_mongodb_data 2>/dev/null || true; \
		$(COMPOSE) up mongodb mongo-express -d; \
		echo "$(GREEN)MongoDB reset!$(NC)"; \
	else \
		echo "$(YELLOW)Reset cancelled.$(NC)"; \
	fi

reset-keycloak: ## Reset Keycloak database (re-imports realm from export files)
	@echo "$(YELLOW)Resetting Keycloak database...$(NC)"
	$(COMPOSE) stop keycloak
	$(COMPOSE) rm -f keycloak
	docker volume rm lablet-cloud-manager_keycloak_data 2>/dev/null || true
	$(COMPOSE) up keycloak -d
	@echo "$(YELLOW)Waiting for Keycloak to start (40s)...$(NC)"
	@sleep 40
	@echo "$(YELLOW)Disabling SSL requirement on master and lablet-cloud-manager realms...$(NC)"
	docker exec lablet-cloud-manager-keycloak-1 /opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080 --realm master --user admin --password admin
	docker exec lablet-cloud-manager-keycloak-1 /opt/keycloak/bin/kcadm.sh update realms/master -s sslRequired=NONE
	docker exec lablet-cloud-manager-keycloak-1 /opt/keycloak/bin/kcadm.sh update realms/lablet-cloud-manager -s sslRequired=NONE
	@echo "$(GREEN)Keycloak database reset and SSL disabled for HTTP access!$(NC)"

reset-etcd: ## Reset etcd data (clears leader election and state)
	@echo "$(RED)WARNING: This will delete all etcd data!$(NC)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		$(COMPOSE) down etcd; \
		docker volume rm lablet-cloud-manager_etcd_data 2>/dev/null || true; \
		$(COMPOSE) up etcd -d; \
		echo "$(GREEN)etcd reset!$(NC)"; \
	else \
		echo "$(YELLOW)Reset cancelled.$(NC)"; \
	fi

urls: ## Display application and service URLs
	@echo ""
	@echo "$(YELLOW)Microservices:$(NC)"
	@echo "  Control Plane API:     $(APP_URL)"
	@echo "  API Docs:              $(API_DOCS_URL)"
	@echo "  Resource Scheduler:    http://localhost:$(RESOURCE_SCHEDULER_PORT)"
	@echo "  Lablet Controller:     http://localhost:$(LABLET_CONTROLLER_PORT)"
	@echo "  Worker Controller:     http://localhost:$(WORKER_CONTROLLER_PORT)"
	@echo "  Scenario Engine:       http://localhost:$(SCENARIO_ENGINE_PORT)"
	@echo ""
	@echo "$(YELLOW)Infrastructure:$(NC)"
	@echo "  etcd:                  $(ETCD_URL)"
	@echo "  MongoDB:               $(MONGO_URL)"
	@echo "  MongoDB Express:       $(MONGO_EXPRESS_URL)"
	@echo "  Keycloak Admin:        $(KEYCLOAK_URL) (admin/admin)"
	@echo "  Event Player:          $(EVENT_PLAYER_URL)"
	@echo ""
	@echo "$(YELLOW)Observability:$(NC)"
	@echo "  OTEL gRPC:             $(OTEL_GRPC_URL)"
	@echo "  OTEL HTTP:             $(OTEL_HTTP_URL)"
	@echo ""
	@echo "$(YELLOW)Debug Ports:$(NC)"
	@echo "  Control Plane API:     5680"
	@echo "  Resource Scheduler:    5681"
	@echo "  Lablet Controller:     5682"
	@echo "  Worker Controller:     5683"
	@echo "  Scenario Engine:       5684"
	@echo ""
	@echo "  Documentation:         http://127.0.0.1:8000/lablet-cloud-manager/"

# ==============================================================================
# SHARED AIX NETWORK MODE
# ==============================================================================
# These targets run LCM services connecting to AIX's shared infrastructure
# on the aix_aix-net network (Keycloak, MongoDB, Redis, OTEL, Events Player).

##@ Shared AIX Network

check-aix-net: ## Check if aix_aix-net network exists
	@if ! docker network inspect aix_aix-net >/dev/null 2>&1; then \
		echo "$(RED)Error: aix_aix-net network not found!$(NC)"; \
		echo "$(YELLOW)Start AIX infrastructure first:$(NC)"; \
		echo "  cd ../aix && make up"; \
		exit 1; \
	fi
	@echo "$(GREEN)aix_aix-net network found$(NC)"

up-shared: check-aix-net ## Start LCM services using shared AIX infrastructure (aix_aix-net)
	@echo "$(BLUE)Starting LCM services on shared aix_aix-net...$(NC)"
	$(SHARED_COMPOSE) up -d
	@echo "$(GREEN)LCM services started on aix_aix-net!$(NC)"
	@$(MAKE) urls-shared

down-shared: ## Stop LCM services (shared mode)
	@echo "$(BLUE)Stopping LCM services (shared mode)...$(NC)"
	$(SHARED_COMPOSE) down
	@echo "$(GREEN)LCM services stopped!$(NC)"

logs-shared: ## Show logs from LCM services (shared mode)
	$(SHARED_COMPOSE) logs -f

logs-shared-api: ## Show logs from control-plane-api (shared mode)
	$(SHARED_COMPOSE) logs -f control-plane-api

logs-shared-scheduler: ## Show logs from resource-scheduler (shared mode)
	$(SHARED_COMPOSE) logs -f resource-scheduler

logs-shared-lablet: ## Show logs from lablet-controller (shared mode)
	$(SHARED_COMPOSE) logs -f lablet-controller

logs-shared-worker: ## Show logs from worker-controller (shared mode)
	$(SHARED_COMPOSE) logs -f worker-controller

logs-shared-scenario: ## Show logs from scenario-engine (shared mode)
	$(SHARED_COMPOSE) logs -f scenario-engine

ps-shared: ## Show running LCM containers (shared mode)
	$(SHARED_COMPOSE) ps

restart-shared: ## Restart LCM services (shared mode, with refreshed environment variables)
	@echo "$(BLUE)Restarting LCM services (shared mode)...$(NC)"
	$(SHARED_COMPOSE) up -d --force-recreate
	@echo "$(GREEN)LCM services restarted with refreshed environment variables!$(NC)"

restart-shared-service: ## Restart a single LCM service (shared mode, usage: make restart-shared-service SERVICE=service_name)
	@if [ -z "$(SERVICE)" ]; then \
		echo "$(RED)Please specify SERVICE=<service_name>$(NC)"; \
		echo "Available services:"; \
		$(SHARED_COMPOSE) config --services; \
		exit 1; \
	fi
	@echo "$(BLUE)Restarting service '$(SERVICE)' (shared mode)...$(NC)"
	$(SHARED_COMPOSE) up -d --force-recreate $(SERVICE)
	@echo "$(GREEN)Service '$(SERVICE)' restarted!$(NC)"

rebuild-shared: ## Rebuild and restart LCM services (shared mode)
	@echo "$(BLUE)Rebuilding LCM services (shared mode)...$(NC)"
	$(SHARED_COMPOSE) build --no-cache
	$(SHARED_COMPOSE) up -d --force-recreate
	@echo "$(GREEN)LCM services rebuilt!$(NC)"
	@$(MAKE) urls-shared

dev-shared: check-aix-net ## Build and start LCM services with live logs (shared mode)
	@echo "$(BLUE)Starting LCM development environment (shared mode)...$(NC)"
	$(SHARED_COMPOSE) up --build

urls-shared: ## Display URLs when running in shared mode
	@echo ""
	@echo "$(BLUE)=== LCM Running in Shared AIX Network Mode ===$(NC)"
	@echo ""
	@echo "$(YELLOW)LCM Microservices:$(NC)"
	@echo "  Control Plane API:     http://localhost:$(APP_PORT)"
	@echo "  API Docs:              http://localhost:$(APP_PORT)/api/docs"
	@echo "  Resource Scheduler:    http://localhost:$(RESOURCE_SCHEDULER_PORT)"
	@echo "  Lablet Controller:     http://localhost:$(LABLET_CONTROLLER_PORT)"
	@echo "  Worker Controller:     http://localhost:$(WORKER_CONTROLLER_PORT)"
	@echo "  Scenario Engine:       http://localhost:$(SCENARIO_ENGINE_PORT)"
	@echo ""
	@echo "$(YELLOW)LCM-Specific Infrastructure:$(NC)"
	@echo "  etcd:                  http://localhost:2379"
	@echo "  MongoDB Express:       http://localhost:8023"
	@echo ""
	@echo "$(YELLOW)Shared AIX Infrastructure (aix_aix-net):$(NC)"
	@echo "  Keycloak Admin:        http://localhost:8041 (admin/admin)"
	@echo "  MongoDB:               mongodb://localhost:27017"
	@echo "  Redis:                 redis://localhost:6379"
	@echo "  OTEL Collector:        grpc://localhost:4317"
	@echo "  Events Player:         http://localhost:8047"
	@echo "  Mongo Express (AIX):   http://localhost:8081"
	@echo ""
	@echo "$(YELLOW)Debug Ports:$(NC)"
	@echo "  Control Plane API:     5680"
	@echo "  Resource Scheduler:    5681"
	@echo "  Lablet Controller:     5682"
	@echo "  Worker Controller:     5683"
	@echo "  Scenario Engine:       5684"

reset-etcd-shared: ## Reset LCM etcd data (shared mode)
	@echo "$(RED)WARNING: This will delete all LCM etcd data!$(NC)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		$(SHARED_COMPOSE) down lcm-etcd; \
		docker volume rm lcm-etcd-data 2>/dev/null || true; \
		$(SHARED_COMPOSE) up lcm-etcd -d; \
		echo "$(GREEN)LCM etcd reset!$(NC)"; \
	else \
		echo "$(YELLOW)Reset cancelled.$(NC)"; \
	fi

# ==============================================================================
# MICROSERVICE-SPECIFIC COMMANDS
# ==============================================================================

##@ Control Plane API

api-install: ## Install control-plane-api dependencies
	@echo "$(BLUE)Installing control-plane-api dependencies...$(NC)"
	cd $(CONTROL_PLANE_DIR) && poetry install
	@echo "$(GREEN)Dependencies installed!$(NC)"

api-install-ui: ## Install control-plane-api UI dependencies
	@echo "$(BLUE)Installing UI dependencies...$(NC)"
	cd $(CONTROL_PLANE_DIR)/ui && npm install
	@echo "$(GREEN)UI dependencies installed!$(NC)"

api-build-ui: ## Build control-plane-api frontend
	@echo "$(BLUE)Building frontend assets...$(NC)"
	cd $(CONTROL_PLANE_DIR)/ui && npm run build
	@echo "$(GREEN)Frontend assets built!$(NC)"

api-run: api-build-ui ## Run control-plane-api locally
	@echo "$(BLUE)Starting Control Plane API...$(NC)"
	@echo "$(GREEN)Access at: http://localhost:8000$(NC)"
	cd $(CONTROL_PLANE_DIR) && PYTHONPATH=. poetry run uvicorn main:create_app --factory --host 0.0.0.0 --port 8000 --reload

api-test: ## Run control-plane-api tests
	@echo "$(BLUE)Running control-plane-api tests...$(NC)"
	cd $(CONTROL_PLANE_DIR) && poetry run pytest

api-lint: ## Run control-plane-api linting
	@echo "$(BLUE)Running control-plane-api linting...$(NC)"
	cd $(CONTROL_PLANE_DIR) && poetry run ruff check .

api-format: ## Format control-plane-api code
	@echo "$(BLUE)Formatting control-plane-api code...$(NC)"
	cd $(CONTROL_PLANE_DIR) && poetry run black .

##@ Resource Scheduler Service

resource-scheduler-install: ## Install resource-scheduler dependencies
	@echo "$(BLUE)Installing resource-scheduler dependencies...$(NC)"
	cd $(RESOURCE_SCHEDULER_DIR) && poetry install
	@echo "$(GREEN)Dependencies installed!$(NC)"

resource-scheduler-run: ## Run resource-scheduler locally
	@echo "$(BLUE)Starting Resource Scheduler...$(NC)"
	cd $(RESOURCE_SCHEDULER_DIR) && PYTHONPATH=. poetry run python main.py

resource-scheduler-test: ## Run resource-scheduler tests
	@echo "$(BLUE)Running resource-scheduler tests...$(NC)"
	cd $(RESOURCE_SCHEDULER_DIR) && poetry run pytest

resource-scheduler-lint: ## Run resource-scheduler linting
	@echo "$(BLUE)Running resource-scheduler linting...$(NC)"
	cd $(RESOURCE_SCHEDULER_DIR) && poetry run ruff check .

##@ Lablet Controller Service

lablet-controller-install: ## Install lablet-controller dependencies
	@echo "$(BLUE)Installing lablet-controller dependencies...$(NC)"
	cd $(LABLET_CONTROLLER_DIR) && poetry install
	@echo "$(GREEN)Dependencies installed!$(NC)"

lablet-controller-run: ## Run lablet-controller locally
	@echo "$(BLUE)Starting Lablet Controller...$(NC)"
	cd $(LABLET_CONTROLLER_DIR) && PYTHONPATH=. poetry run python main.py

lablet-controller-test: ## Run lablet-controller tests
	@echo "$(BLUE)Running lablet-controller tests...$(NC)"
	cd $(LABLET_CONTROLLER_DIR) && poetry run pytest

lablet-controller-lint: ## Run lablet-controller linting
	@echo "$(BLUE)Running lablet-controller linting...$(NC)"
	cd $(LABLET_CONTROLLER_DIR) && poetry run ruff check .

##@ Worker Controller Service

worker-controller-install: ## Install worker-controller dependencies
	@echo "$(BLUE)Installing worker-controller dependencies...$(NC)"
	cd $(WORKER_CONTROLLER_DIR) && poetry install
	@echo "$(GREEN)Dependencies installed!$(NC)"

worker-controller-run: ## Run worker-controller locally
	@echo "$(BLUE)Starting Worker Controller...$(NC)"
	cd $(WORKER_CONTROLLER_DIR) && PYTHONPATH=. poetry run python main.py

worker-controller-test: ## Run worker-controller tests
	@echo "$(BLUE)Running worker-controller tests...$(NC)"
	cd $(WORKER_CONTROLLER_DIR) && poetry run pytest

worker-controller-lint: ## Run worker-controller linting
	@echo "$(BLUE)Running worker-controller linting...$(NC)"
	cd $(WORKER_CONTROLLER_DIR) && poetry run ruff check .

##@ Scenario Engine Service

scenario-engine-install: ## Install scenario-engine dependencies
	@echo "$(BLUE)Installing scenario-engine dependencies...$(NC)"
	cd $(SCENARIO_ENGINE_DIR) && poetry install
	@echo "$(GREEN)Dependencies installed!$(NC)"

scenario-engine-run: ## Run scenario-engine locally
	@echo "$(BLUE)Starting Scenario Engine...$(NC)"
	cd $(SCENARIO_ENGINE_DIR) && PYTHONPATH=. poetry run python main.py

scenario-engine-test: ## Run scenario-engine tests
	@echo "$(BLUE)Running scenario-engine tests...$(NC)"
	cd $(SCENARIO_ENGINE_DIR) && poetry run pytest

scenario-engine-lint: ## Run scenario-engine linting
	@echo "$(BLUE)Running scenario-engine linting...$(NC)"
	cd $(SCENARIO_ENGINE_DIR) && poetry run ruff check .

##@ All Services

install-all: api-install resource-scheduler-install lablet-controller-install worker-controller-install scenario-engine-install ## Install dependencies for all services
	@echo "$(GREEN)All dependencies installed!$(NC)"

test-all: api-test resource-scheduler-test lablet-controller-test worker-controller-test scenario-engine-test ## Run tests for all services
	@echo "$(GREEN)All tests complete!$(NC)"

lint-all: api-lint resource-scheduler-lint lablet-controller-lint worker-controller-lint scenario-engine-lint ## Run linting for all services
	@echo "$(GREEN)All linting complete!$(NC)"

##@ Testing & Quality (Legacy - use api-test, resource-scheduler-test, lablet-controller-test)

test: api-test ## Run control-plane-api tests (default)

test-unit: ## Run unit tests on control-plane-api
	@echo "$(BLUE)Running unit tests...$(NC)"
	cd $(CONTROL_PLANE_DIR) && poetry run pytest -m unit

test-domain: ## Run domain tests on control-plane-api
	@echo "$(BLUE)Running domain tests...$(NC)"
	cd $(CONTROL_PLANE_DIR) && poetry run pytest tests/domain/ -v

test-command: ## Run command tests on control-plane-api
	@echo "$(BLUE)Running command tests...$(NC)"
	cd $(CONTROL_PLANE_DIR) && poetry run pytest -m command

test-query: ## Run query tests on control-plane-api
	@echo "$(BLUE)Running query tests...$(NC)"
	cd $(CONTROL_PLANE_DIR) && poetry run pytest -m query

test-application: ## Run application tests on control-plane-api
	@echo "$(BLUE)Running application tests...$(NC)"
	cd $(CONTROL_PLANE_DIR) && poetry run pytest tests/application -v

test-cov: ## Run tests with coverage on control-plane-api
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	cd $(CONTROL_PLANE_DIR) && poetry run pytest --cov=. --cov-report=html --cov-report=term

lint: api-lint ## Run linting on control-plane-api (default)

format: api-format ## Format control-plane-api code (default)

install-hooks: ## Install pre-commit git hooks
	@echo "$(BLUE)Installing pre-commit git hooks...$(NC)"
	cd $(CONTROL_PLANE_DIR) && poetry run pre-commit install --install-hooks
	@echo "$(GREEN)Git hooks installed successfully.$(NC)"
	@echo "$(GREEN)Git hooks installed successfully.$(NC)"

##@ Cleanup

clean: ## Clean up generated files and caches
	@echo "$(BLUE)Cleaning up...$(NC)"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	rm -rf .coverage htmlcov/ 2>/dev/null || true
	rm -rf ui/.parcel-cache 2>/dev/null || true
	@echo "$(GREEN)Cleanup complete!$(NC)"

clean-all: clean docker-clean ## Clean everything including Docker volumes

##@ Documentation

docs-install: ## Install MkDocs and dependencies
	@echo "$(BLUE)Installing MkDocs dependencies...$(NC)"
	pip install mkdocs mkdocs-material mkdocs-mermaid2-plugin
	@echo "$(GREEN)MkDocs dependencies installed!$(NC)"

docs-update-config: ## Update mkdocs.yml from .env variables
	@echo "$(BLUE)Updating mkdocs.yml from environment variables...$(NC)"
	@python3 scripts/update-mkdocs-config.py

docs-lint: ## Lint markdown files in docs folder
	@echo "$(BLUE)Linting markdown documentation...$(NC)"
	poetry run pre-commit run markdownlint --files $(DOCS_FOLDER)/**/*.md

docs-serve: docs-update-config ## Serve documentation locally with live reload
	@echo "$(BLUE)Starting documentation server...$(NC)"
	@echo "$(GREEN)Access at: http://127.0.0.1:$(DOCS_DEV_PORT)$(NC)"
	@echo "$(YELLOW)Site: $(DOCS_SITE_NAME)$(NC)"
	mkdocs serve --dev-addr=127.0.0.1:$(DOCS_DEV_PORT)

docs-build: docs-update-config ## Build documentation site
	@echo "$(BLUE)Building documentation...$(NC)"
	@echo "$(YELLOW)Site: $(DOCS_SITE_NAME)$(NC)"
	@echo "$(YELLOW)URL: $(DOCS_SITE_URL)$(NC)"
	mkdocs build --site-dir site
	@echo "$(GREEN)Documentation built in site/ directory$(NC)"

docs-deploy: docs-update-config ## Deploy documentation to GitHub Pages
	@echo "$(BLUE)Deploying documentation to GitHub Pages...$(NC)"
	@echo "$(YELLOW)Site: $(DOCS_SITE_NAME)$(NC)"
	@echo "$(YELLOW)URL: $(DOCS_SITE_URL)$(NC)"
	mkdocs gh-deploy --force
	@echo "$(GREEN)Documentation deployed!$(NC)"

docs-clean: ## Clean documentation build artifacts
	@echo "$(BLUE)Cleaning documentation build...$(NC)"
	rm -rf site/
	@echo "$(GREEN)Documentation build cleaned!$(NC)"

docs-config: ## Show current documentation configuration
	@echo "$(BLUE)Documentation Configuration:$(NC)"
	@echo "  $(YELLOW)Site Name:$(NC) $(DOCS_SITE_NAME)"
	@echo "  $(YELLOW)Site URL:$(NC)  $(DOCS_SITE_URL)"
	@echo "  $(YELLOW)Docs Folder:$(NC) $(DOCS_FOLDER)"
	@echo "  $(YELLOW)Dev Port:$(NC)   $(DOCS_DEV_PORT)"

##@ Environment Setup

setup: api-install api-install-ui api-build-ui install-hooks resource-scheduler-install lablet-controller-install worker-controller-install scenario-engine-install ## Complete setup for new developers
	@echo "$(GREEN)✅ Setup complete!$(NC)"
	@echo ""
	@echo "$(YELLOW)Quick Start:$(NC)"
	@echo "  make api-run          - Run control-plane-api locally"
	@echo "  make up               - Run with Docker (all services)"
	@echo "  make help             - Show all commands"

env-check: ## Check environment requirements
	@echo "$(BLUE)Checking environment...$(NC)"
	@command -v python3.11 >/dev/null 2>&1 || { echo "$(RED)❌ Python 3.11 not found$(NC)"; exit 1; }
	@command -v poetry >/dev/null 2>&1 || { echo "$(RED)❌ Poetry not found$(NC)"; exit 1; }
	@command -v node >/dev/null 2>&1 || { echo "$(RED)❌ Node.js not found$(NC)"; exit 1; }
	@command -v docker >/dev/null 2>&1 || { echo "$(RED)❌ Docker not found$(NC)"; exit 1; }
	@command -v docker-compose >/dev/null 2>&1 || { echo "$(RED)❌ Docker Compose not found$(NC)"; exit 1; }
	@echo "$(GREEN)✅ All requirements satisfied!$(NC)"

##@ Information

status: ## Show current status
	@echo "$(BLUE)System Status:$(NC)"
	@echo ""
	@echo "$(YELLOW)Docker Services:$(NC)"
	@docker-compose ps 2>/dev/null || echo "$(RED)Docker services not running$(NC)"
	@echo ""
	@echo "$(YELLOW)Service URLs:$(NC)"
	@$(MAKE) urls

info: ## Show project information
	@echo "$(BLUE)Lablet Cloud Manager - Multi-Service Architecture$(NC)"
	@echo ""
	@echo "$(YELLOW)Microservices:$(NC)"
	@echo "  📱 Control Plane API  - REST API + UI (MongoDB writer)"
	@echo "  📅 Scheduler          - LabletInstance placement decisions"
	@echo "  🎛️  Lablet Controller  - LabletInstance reconciliation + auto-scaling"
	@echo "  🔧 Worker Controller  - CML Worker observation + monitoring"
	@echo "  🎭 Scenario Engine    - Pod automation execution (DSL + adapters)"
	@echo ""
	@echo "$(YELLOW)Docker URLs:$(NC)"
	@echo "  Control Plane API: http://localhost:8020"
	@echo "  API Docs:          http://localhost:8020/api/docs"
	@echo "  Scheduler:         http://localhost:8081"
	@echo "  Lablet Controller: http://localhost:8082"
	@echo "  Worker Controller: http://localhost:8083"
	@echo "  Scenario Engine:   http://localhost:8084"
	@echo "  etcd:              http://localhost:2379"
	@echo "  MongoDB Express:   http://localhost:8023"
	@echo "  Keycloak Admin:    http://localhost:8021 (admin/admin)"
	@echo "  Event Player:      http://localhost:8024"
	@echo ""
	@echo "$(YELLOW)Test Users:$(NC)"
	@echo "  admin/admin123     (Admin - Full Access)"
	@echo "  manager/manager123 (Manager - Department Access)"
	@echo "  user/user123       (User - Assigned Tasks Only)"
	@echo ""
	@echo "$(YELLOW)Documentation:$(NC)"
	@echo "  README.md           - Setup and usage guide"
	@echo "  docs/               - Full documentation (MkDocs)"

# ==============================================================================
# PRODUCTION COMMANDS
# ==============================================================================

##@ Production

prod-up: ## Start production services in the background
	@echo "$(BLUE)Starting production services...$(NC)"
	$(PROD_COMPOSE) up -d
	@echo "$(GREEN)Production services started!$(NC)"

prod-down: ## Stop and remove production services
	@echo "$(BLUE)Stopping production services...$(NC)"
	$(PROD_COMPOSE) down
	@echo "$(GREEN)Production services stopped!$(NC)"

prod-logs: ## Show recent logs from production services (tail 100 lines)
	$(PROD_COMPOSE) logs -f --tail=100

prod-ps: ## Show running production containers
	$(PROD_COMPOSE) ps

prod-restart: ## Restart all production services
	@echo "$(BLUE)Restarting production services...$(NC)"
	$(PROD_COMPOSE) restart
	@echo "$(GREEN)Production services restarted!$(NC)"

prod-restart-service: ## Restart a single production service (usage: make prod-restart-service SERVICE=service_name)
	@if [ -z "$(SERVICE)" ]; then \
		echo "$(RED)Please specify SERVICE=<service_name>$(NC)"; \
		exit 1; \
	fi
	@echo "$(BLUE)Restarting production service '$(SERVICE)'...$(NC)"
	$(PROD_COMPOSE) up -d --force-recreate $(SERVICE)
	@echo "$(GREEN)Production service '$(SERVICE)' restarted!$(NC)"

prod-pull: ## Pull latest images for production services
	@echo "$(BLUE)Pulling latest images...$(NC)"
	$(PROD_COMPOSE) pull
	@echo "$(GREEN)Images pulled!$(NC)"

prod-upgrade: ## Upgrade api and worker to new image tag (pull + recreate)
	@echo "$(BLUE)Upgrading api and worker services to new image...$(NC)"
	@echo "$(YELLOW)Pulling new images...$(NC)"
	$(PROD_COMPOSE) pull api worker
	@echo "$(YELLOW)Recreating api and worker containers...$(NC)"
	$(PROD_COMPOSE) up -d --force-recreate --no-deps api worker
	@echo "$(GREEN)Upgrade complete! Services now running with new image.$(NC)"
	@$(MAKE) prod-ps
