.PHONY: help install install-ui build-ui run test lint format clean

# Default target
.DEFAULT_GOAL := help

# ==============================================================================
# VARIABLES
# ==============================================================================

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

# Application settings
APP_PORT ?= 8080
SERVICE_NAME := control-plane-api

# ==============================================================================
# HELP
# ==============================================================================

##@ General

help: ## Display this help message
	@echo "$(BLUE)Control Plane API - Development Commands$(NC)"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"; printf "Usage:\n  make $(GREEN)<target>$(NC)\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2 } /^##@/ { printf "\n$(YELLOW)%s$(NC)\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

# ==============================================================================
# INSTALLATION
# ==============================================================================

##@ Installation

install: ## Install Python dependencies with Poetry
	@echo "$(BLUE)Installing Python dependencies...$(NC)"
	poetry install
	@echo "$(GREEN)Dependencies installed!$(NC)"

install-ui: ## Install Node.js dependencies for UI
	@echo "$(BLUE)Installing UI dependencies...$(NC)"
	cd ui && npm ci
	@echo "$(GREEN)UI dependencies installed!$(NC)"

link-ui-core: ## Link local @neuroglia/ui-core package for development
	@echo "$(BLUE)Building and linking @neuroglia/ui-core...$(NC)"
	cd ../core/lcm_ui && npm run build
	cd ui && npm install
	@echo "$(GREEN)@neuroglia/ui-core linked!$(NC)"

unlink-ui-core: ## Unlink local @neuroglia/ui-core and reinstall from registry
	@echo "$(BLUE)Unlinking @neuroglia/ui-core...$(NC)"
	cd ui && npm uninstall @neuroglia/ui-core
	cd ui && npm install
	@echo "$(GREEN)@neuroglia/ui-core unlinked!$(NC)"

# ==============================================================================
# BUILD
# ==============================================================================

##@ Build

build-ui: ## Build the frontend UI with Parcel
	@echo "$(BLUE)Building UI...$(NC)"
	cd ui && npm run build
	@echo "$(GREEN)UI built successfully!$(NC)"

# ==============================================================================
# DEVELOPMENT
# ==============================================================================

##@ Development

run: ## Run the API server locally (requires build-ui first)
	@echo "$(BLUE)Starting Control Plane API on port $(APP_PORT)...$(NC)"
	PYTHONPATH=. poetry run uvicorn main:create_app --factory --host 0.0.0.0 --port $(APP_PORT) --reload

run-worker: ## Run the background worker
	@echo "$(BLUE)Starting background worker...$(NC)"
	PYTHONPATH=. poetry run python background_worker.py

dev: build-ui run ## Build UI and run the API server

# ==============================================================================
# TESTING
# ==============================================================================

##@ Testing

test: ## Run all tests (excluding integration tests that need external services)
	@echo "$(BLUE)Running tests...$(NC)"
	PYTHONPATH=. poetry run pytest tests/ -v -m "not integration" --ignore=tests/integration

test-unit: ## Run unit tests only
	@echo "$(BLUE)Running unit tests...$(NC)"
	PYTHONPATH=. poetry run pytest tests/ -v -m "not integration" --ignore=tests/integration

test-integration: ## Run integration tests only (requires Docker services)
	@echo "$(BLUE)Running integration tests...$(NC)"
	PYTHONPATH=. poetry run pytest tests/integration/ -v -m integration

test-all: ## Run ALL tests including integration (requires Docker services)
	@echo "$(BLUE)Running all tests (including integration)...$(NC)"
	PYTHONPATH=. poetry run pytest tests/ -v

test-cov: ## Run tests with coverage report
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	PYTHONPATH=. poetry run pytest tests/ -v --cov=. --cov-report=html --cov-report=term

# ==============================================================================
# CODE QUALITY
# ==============================================================================

##@ Code Quality

lint: ## Run linting with Ruff
	@echo "$(BLUE)Running linting...$(NC)"
	poetry run ruff check .

format: ## Format code with Black and isort
	@echo "$(BLUE)Formatting code...$(NC)"
	poetry run black .
	poetry run ruff check . --fix

type-check: ## Run type checking with mypy
	@echo "$(BLUE)Running type checking...$(NC)"
	poetry run mypy .

# ==============================================================================
# CLEANUP
# ==============================================================================

##@ Cleanup

clean: ## Clean build artifacts and caches
	@echo "$(BLUE)Cleaning up...$(NC)"
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache
	rm -rf htmlcov .coverage
	rm -rf ui/.parcel-cache
	rm -rf static/*.js static/*.css static/*.html static/*.svg
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@echo "$(GREEN)Cleanup complete!$(NC)"
