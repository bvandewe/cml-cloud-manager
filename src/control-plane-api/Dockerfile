# Dockerfile for Control Plane API
# Build context must be set to the repo src/ directory (parent of control-plane-api)
# so that the @neuroglia/ui-core file dependency (../../core/lcm_ui → core/lcm_ui)
# can be resolved during the UI build stage.

# Stage 1: Build UI
FROM node:20 AS ui-build
# Copy the shared @neuroglia/ui-core package first
COPY core/lcm_ui /core/lcm_ui

WORKDIR /app/ui
# Copy the entire UI source code First
COPY control-plane-api/ui .
# Rewrite the file: dependency to point to the /core/lcm_ui copy
RUN sed -i 's|file:../../core/lcm_ui|file:/core/lcm_ui|' package.json
# Install dependencies cleanly (rm -rf first to wipe MacOS node_modules, parcel cache and old lockfile)
RUN rm -rf node_modules .parcel-cache package-lock.json && npm install
# Build the UI - outputs to /static (../../static relative to /app/ui)
RUN npm run build

# Stage 2: Python App
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy Poetry files
COPY control-plane-api/pyproject.toml ./

# Install Poetry and dependencies
# Note: We remove lcm-core path dependency during build since it's mounted at runtime
# We also remove any lock file to ensure fresh dependency resolution after modifying pyproject.toml
RUN pip install poetry && \
    poetry config virtualenvs.create false && \
    sed -i '/lcm-core.*path.*develop/d' pyproject.toml && \
    poetry lock && \
    poetry install --no-interaction --no-ansi --no-root

# Copy application code
COPY control-plane-api/ .

# Copy built UI assets from ui-build stage
# Note: Parcel outputs to ../static from /app/ui, which resolves to /app/static
COPY --from=ui-build /app/static /app/static

# Set Python path
ENV PYTHONPATH=/app:$PYTHONPATH

# Expose port
EXPOSE 8080

# Run the application
# IMPORTANT: --workers 1 is required because background jobs (APScheduler)
# are NOT multi-worker safe. Multiple workers would cause duplicate job execution.
CMD ["uvicorn", "main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
