# Dockerfile for Scenario Engine Service

# Stage 1: Build UI
FROM node:20 AS ui-build
WORKDIR /app/ui
# Copy package files first for caching
COPY ui/package*.json ./
RUN npm install
# Copy the rest of the UI source code
COPY ui .
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
COPY pyproject.toml ./

# Install Poetry and dependencies
# Note: We remove lcm-core path dependency during build since it's mounted at runtime
# We also remove any lock file to ensure fresh dependency resolution after modifying pyproject.toml
# Skip optional 'dsl' group (pyjq requires autotools not available in slim image)
RUN pip install poetry && \
    poetry config virtualenvs.create false && \
    sed -i '/lcm-core.*path.*develop/d' pyproject.toml && \
    poetry lock && \
    poetry install --no-interaction --no-ansi --no-root --without dsl

# Copy application code
COPY . .

# Copy built UI assets from ui-build stage
# Note: Parcel outputs to ../static from /app/ui, which resolves to /app/static
COPY --from=ui-build /app/static /app/static

# Set Python path
ENV PYTHONPATH=/app:$PYTHONPATH

# Expose port (health check endpoint)
EXPOSE 8084

# Run the scenario engine service
CMD ["python", "main.py"]
