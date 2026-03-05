.PHONY: install build build-watch test test-watch test-cov lint lint-fix clean typecheck help

# Default target
.DEFAULT_GOAL := help

# Colors for output
CYAN := \033[0;36m
GREEN := \033[0;32m
YELLOW := \033[0;33m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(CYAN)@neuroglia/ui-core$(NC) - Available commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-15s$(NC) %s\n", $$1, $$2}'
	@echo ""

install: ## Install dependencies
	npm install

build: ## Build the package (ESM + UMD + types)
	npm run build

build-watch: ## Build in watch mode
	npm run build:watch

test: ## Run tests
	npm run test

test-watch: ## Run tests in watch mode
	npm run test:watch

test-cov: ## Run tests with coverage
	npm run test:coverage

lint: ## Run ESLint
	npm run lint

lint-fix: ## Run ESLint with auto-fix
	npm run lint:fix

typecheck: ## Run TypeScript type checking
	npm run typecheck

clean: ## Clean build artifacts
	rm -rf dist node_modules/.cache coverage
	@echo "$(GREEN)✓ Cleaned build artifacts$(NC)"

clean-all: clean ## Clean everything including node_modules
	rm -rf node_modules
	@echo "$(GREEN)✓ Cleaned node_modules$(NC)"

# Development workflow
dev: install build-watch ## Install deps and start watch mode

# CI workflow
ci: install lint typecheck test build ## Full CI pipeline
	@echo "$(GREEN)✓ CI pipeline complete$(NC)"

# Publishing
pack: build ## Create npm package tarball for testing
	npm pack
	@echo "$(GREEN)✓ Package tarball created$(NC)"

# Verification
verify: build ## Verify the build works correctly
	@echo "Checking dist files..."
	@test -f dist/index.esm.js || (echo "$(YELLOW)Missing dist/index.esm.js$(NC)" && exit 1)
	@test -f dist/index.umd.js || (echo "$(YELLOW)Missing dist/index.umd.js$(NC)" && exit 1)
	@test -f dist/types/index.d.ts || (echo "$(YELLOW)Missing dist/types/index.d.ts$(NC)" && exit 1)
	@echo "$(GREEN)✓ Build verification passed$(NC)"
