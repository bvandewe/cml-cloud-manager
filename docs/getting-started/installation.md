# Installation

This guide will walk you through setting up the project for local development.

## Prerequisites

Before you begin, ensure you have the following installed:

- **Docker and Docker Compose**: For running the application and its services.
- **Python 3.11+**: Backend runtime (FastAPI + Neuroglia CQRS framework).
- **Poetry**: Dependency management for Python.
- **Node.js 18+ & npm**: Building frontend assets (SSE client, UI scripts).

### Optional (for local telemetry stack)

- **Docker resources**: Sufficient memory for Prometheus, Grafana, Tempo, and OTEL Collector.

### Real-Time Updates (SSE)

No extra prerequisite is required for Server-Sent Events. The SSE stream is enabled by default and served from the application process. When the app is running you will see a connection status badge on the Workers page indicating `Live`, `Connecting`, or `Disconnected`.

See the architecture overview of this feature: [Real-Time Updates](../architecture/realtime-updates.md).

## Installation Steps

1. **Clone the repository**:

    ```bash
    git clone https://github.com/bvandewe/lablet-cloud-manager.git
    cd lablet-cloud-manager
    ```

2. **Install Python dependencies**:
    Use Poetry to install the required Python packages.

    ```bash
    make install
    ```

    This command will create a virtual environment and install all dependencies defined in `pyproject.toml`.

3. **Install pre-commit hooks**:
    This project uses pre-commit hooks to enforce code quality. Install them by running:

    ```bash
    make install-hooks
    ```

4. **Install UI dependencies**:
    The frontend assets are built using Node.js.

    ```bash
    make install-ui
    ```

## Next Steps

- Run the application: follow [Running the App](running-the-app.md)
- Verify SSE connectivity: open the Workers page and confirm the status badge shows `Live`.
- Trigger a real-time event: create or modify a worker and observe the toast and list refresh.
