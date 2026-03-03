# Control Plane API

The Control Plane API is the central gateway for the Lablet Cloud Manager system. It provides:

- REST API endpoints for LabletDefinition, LabletInstance, and Worker management
- Bootstrap 5 SPA with Server-Side Events (SSE) for real-time updates
- Authentication via Keycloak (OAuth2/OIDC)
- Background jobs for worker monitoring and metrics collection
- CloudEvents publishing for external integration

## Architecture

This service follows Clean Architecture with the Neuroglia framework:

```
api/            # REST controllers, dependencies, auth services
application/    # Commands, queries, DTOs, background jobs, settings
domain/         # Entities, aggregates, repositories (interfaces)
infrastructure/ # Session stores, technical adapters
integration/    # MongoDB repositories, AWS EC2/CML API clients
observability/  # OpenTelemetry instrumentation
ui/             # Bootstrap 5 SPA source (Parcel bundler)
```

## Development

### Prerequisites

- Python 3.11+
- Poetry
- Node.js 20+ (for UI build)

### Setup

```bash
# Install Python dependencies
make install

# Install UI dependencies
make install-ui

# Build UI assets
make build-ui

# Run locally
make run
```

### Testing

```bash
# Run all tests
make test

# Run with coverage
make test-cov
```

## Environment Variables

See the main project README for full environment variable documentation.

Key variables:

- `KEYCLOAK_URL` - Keycloak server URL
- `CONNECTION_STRINGS` - MongoDB connection string
- `REDIS_URL` - Redis URL for session storage
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` - AWS credentials
