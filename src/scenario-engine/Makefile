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
APP_PORT ?= 8004
SERVICE_NAME := scenario-engine

# ==============================================================================
# HELP
# ==============================================================================

##@ General

help: ## Display this help message
	@echo "$(BLUE)Scenario Engine Service - Development Commands$(NC)"
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
	cd ui && npm install
	@echo "$(GREEN)UI dependencies installed!$(NC)"

# ==============================================================================
# BUILD
# ==============================================================================

##@ Build

build-ui: ## Build the frontend UI with Parcel
	@echo "$(BLUE)Building UI...$(NC)"
	@if [ ! -d "ui/node_modules" ]; then \
		echo "$(YELLOW)node_modules not found, running npm install...$(NC)"; \
		cd ui && npm install; \
	fi
	cd ui && npm run build
	@echo "$(GREEN)UI built successfully!$(NC)"

# ==============================================================================
# DEVELOPMENT
# ==============================================================================

##@ Development

run: ## Run the scenario-engine service locally (requires build-ui first)
	@echo "$(BLUE)Starting Scenario Engine Service on port $(APP_PORT)...$(NC)"
	PYTHONPATH=. poetry run python main.py

debug: ## Run with debugpy for VS Code debugging
	@echo "$(BLUE)Starting Scenario Engine Service in debug mode...$(NC)"
	PYTHONPATH=. poetry run python -m debugpy --listen 0.0.0.0:5684 --wait-for-client main.py

dev: build-ui run ## Build UI and run the service

# ==============================================================================
# TESTING
# ==============================================================================

##@ Testing

test: ## Run tests with pytest
	@echo "$(BLUE)Running tests...$(NC)"
	poetry run pytest tests/ -v
	@echo "$(GREEN)Tests complete!$(NC)"

test-cov: ## Run tests with coverage report
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	poetry run pytest tests/ -v --cov=. --cov-report=html --cov-report=term
	@echo "$(GREEN)Coverage report generated in htmlcov/$(NC)"

test-unit: ## Run only unit tests
	@echo "$(BLUE)Running unit tests...$(NC)"
	poetry run pytest tests/ -v -m unit

test-integration: ## Run only integration tests
	@echo "$(BLUE)Running integration tests...$(NC)"
	poetry run pytest tests/ -v -m integration

# ==============================================================================
# CODE QUALITY
# ==============================================================================

##@ Code Quality

lint: ## Run Ruff linting
	@echo "$(BLUE)Running linting...$(NC)"
	poetry run ruff check .
	@echo "$(GREEN)Linting passed!$(NC)"

format: ## Format code with Black and Ruff
	@echo "$(BLUE)Formatting code...$(NC)"
	poetry run ruff format .
	poetry run ruff check --fix .
	@echo "$(GREEN)Code formatted!$(NC)"

type-check: ## Run Pyright type checking
	@echo "$(BLUE)Running type checks...$(NC)"
	poetry run pyright .
	@echo "$(GREEN)Type checks passed!$(NC)"

# ==============================================================================
# CLEANUP
# ==============================================================================

##@ Cleanup

clean: ## Remove build artifacts
	@echo "$(BLUE)Cleaning build artifacts...$(NC)"
	rm -rf __pycache__ .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@echo "$(GREEN)Cleaned!$(NC)"
