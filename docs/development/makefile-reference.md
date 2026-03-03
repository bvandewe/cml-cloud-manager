# Makefile Quick Reference

This document provides a quick reference for all available `make` commands in the Cml Cloud Manager project.

## 🚀 Quick Start Commands

```bash
make setup        # Complete setup (install dependencies + build UI + hooks)
make run          # Run application locally
make up           # Run with Docker
make help         # Show all commands
```

## 📋 All Commands

### General

- `make help` - Display help message with all commands

### Docker Commands

| Command | Description |
|---------|-------------|
| `make build` | Build Docker images for all services |
| `make up` | Start services in background |
| `make down` | Stop and remove services |
| `make start` | Start existing containers |
| `make stop` | Stop running containers |
| `make restart` | Restart all services |
| `make restart-service SERVICE=<name>` | Restart a single Docker service |
| `make dev` | Build and start services with live logs |
| `make rebuild` | Rebuild services from scratch (no cache) |
| `make logs` | Show logs from all services |
| `make logs-app` | Show logs from app service only |
| `make ps` | Show running containers |
| `make docker-clean` | ⚠️ Stop services and remove volumes (deletes data!) |
| `make urls` | Display application and service URLs |

### Local Development

| Command | Description |
|---------|-------------|
| `make install` | Install Python dependencies with Poetry |
| `make install-ui` | Install Node.js dependencies for UI |
| `make build-ui` | Build frontend assets |
| `make dev-ui` | Start UI development server with hot-reload |
| `make run` | Run the application locally (requires build-ui first) |
| `make run-debug` | Run with debug logging |

### Testing & Quality

| Command | Description |
|---------|-------------|
| `make test` | Run all tests |
| `make test-unit` | Run unit tests only |
| `make test-domain` | Run domain layer tests |
| `make test-command` | Run command tests |
| `make test-query` | Run query tests |
| `make test-application` | Run application layer tests |
| `make test-cov` | Run tests with coverage report (HTML + terminal) |
| `make lint` | Run linting checks with Ruff |
| `make format` | Format code with Black |
| `make install-hooks` | Install pre-commit git hooks |

### Cleanup

| Command | Description |
|---------|-------------|
| `make clean` | Clean up generated files and caches |
| `make clean-all` | Clean everything including Docker volumes |

### Documentation

| Command | Description |
|---------|-------------|
| `make docs-install` | Install MkDocs and dependencies |
| `make docs-update-config` | Update mkdocs.yml from .env variables |
| `make docs-serve` | Serve documentation locally with live reload |
| `make docs-build` | Build documentation site |
| `make docs-deploy` | Deploy documentation to GitHub Pages |
| `make docs-clean` | Clean documentation build artifacts |
| `make docs-config` | Show current documentation configuration |

### Environment Setup

| Command | Description |
|---------|-------------|
| `make setup` | Complete setup for new developers |
| `make env-check` | Check environment requirements |

### Information

| Command | Description |
|---------|-------------|
| `make status` | Show current environment status |
| `make info` | Show project information and URLs |

## 🎯 Common Workflows

### First Time Setup

```bash
# Clone the repository (if needed)
git clone <repository-url>
cd lablet-cloud-manager

# Check environment
make env-check

# Complete setup
make setup

# Run the application
make run
```

### Daily Development (Local)

```bash
# Start UI development server (Terminal 1)
make dev-ui

# Start backend with hot-reload (Terminal 2)
make run
```

### Daily Development (Docker)

```bash
# Start all services
make up

# View logs
make logs

# Stop services when done
make down
```

### Testing Workflow

```bash
# Run all tests
make test

# Run specific test layers
make test-domain        # Domain entities
make test-application   # Commands and queries
make test-unit          # Unit tests only

# Run tests with coverage
make test-cov

# View coverage report
open htmlcov/index.html  # macOS
```

### Before Committing

```bash
# Format code
make format

# Run linting
make lint

# Run tests
make test-cov

# Clean up
make clean
```

### Troubleshooting

```bash
# Check status
make status

# Rebuild Docker from scratch
make rebuild

# Clean everything and start fresh
make clean-all
make setup
```

## 🔗 Service URLs

When running locally (`make run`):

- App: http://localhost:8000
- API Docs: http://localhost:8000/api/docs

When running with Docker (`make up`):

- App: http://localhost:8020
- API Docs: http://localhost:8020/api/docs
- Keycloak: http://localhost:8021
- MongoDB: mongodb://localhost:8022
- MongoDB Express: http://localhost:8023
- Event Player: http://localhost:8025

Use `make urls` to display all service URLs with configured ports.

## 🎨 Color-Coded Output

The Makefile uses color-coded output for better readability:

- 🔵 **Blue** - Informational messages
- 🟢 **Green** - Success messages
- 🟡 **Yellow** - Warning messages
- 🔴 **Red** - Error messages

## 💡 Tips

1. **Tab Completion**: Most shells support tab completion for make targets
2. **Parallel Execution**: Some targets can be run in parallel (e.g., `dev-ui` and `run`)
3. **Environment Variables**: Commands respect `.env` file settings
4. **Safety First**: Destructive commands (like `docker-clean`) require confirmation

## 📚 Additional Resources

- See `README.md` for comprehensive documentation
- See `SETUP_COMPLETE.md` for setup summary
- Run `make info` for quick reference of URLs and test users
