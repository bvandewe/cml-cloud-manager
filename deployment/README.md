# Deployment

This directory contains the configuration and resources for deploying the Lablet Cloud Manager.

## Deployment Options

### 1. Docker Compose (Recommended)

The primary deployment method for production is Docker Compose. It orchestrates the full stack including the application, database, authentication, and observability services.

- **Directory**: `deployment/docker-compose/`
- **Guide**: [Production Docker Compose Setup](docker-compose/README.md)

### 2. Helm (Kubernetes)

A Helm chart is provided for Kubernetes deployments.

- **Directory**: `deployment/helm/`
- **Note**: The Helm chart is maintained separately and may not include all the latest production hardening features found in the Docker Compose setup.

## Sub-components

- **[Nginx](nginx/README.md)**: Reverse proxy configuration.
- **[Keycloak](keycloak/README.md)**: Identity provider configuration.
- **[Grafana](grafana/README.md)**: Dashboards and visualization.
- **[OpenTelemetry](otel/README.md)**: Observability stack configuration.
