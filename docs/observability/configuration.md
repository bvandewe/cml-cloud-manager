# Observability Configuration

This guide covers all configuration options for observability in the Cml Cloud Manager.

## Table of Contents

- [Environment Variables](#environment-variables)
- [OTEL Collector Configuration](#otel-collector-configuration)
- [Application Configuration](#application-configuration)
- [Backend Configuration](#backend-configuration)

## Environment Variables

Configure observability via environment variables in `.env` file.

### Service Identification

```bash
# Service name (appears in traces and metrics)
OTEL_SERVICE_NAME=lablet-cloud-manager

# Service version (for tracking deployments)
OTEL_SERVICE_VERSION=1.0.0

# Service namespace (for multi-tenant environments)
OTEL_SERVICE_NAMESPACE=production
```

### OTLP Exporter

```bash
# OTEL Collector endpoint
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317

# Protocol: grpc or http/protobuf
OTEL_EXPORTER_OTLP_PROTOCOL=grpc

# Timeout for exporting (milliseconds)
OTEL_EXPORTER_OTLP_TIMEOUT=10000

# Headers (for authentication)
OTEL_EXPORTER_OTLP_HEADERS=api-key=your-key-here
```

### Traces Configuration

```bash
# Exporter: otlp, console, none
OTEL_TRACES_EXPORTER=otlp

# Sampling: always_on, always_off, traceidratio, parentbased_always_on
OTEL_TRACES_SAMPLER=parentbased_always_on

# Sampling ratio (0.0 to 1.0) when using traceidratio
OTEL_TRACES_SAMPLER_ARG=1.0

# Maximum attributes per span
OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT=128

# Maximum events per span
OTEL_SPAN_EVENT_COUNT_LIMIT=128

# Maximum links per span
OTEL_SPAN_LINK_COUNT_LIMIT=128
```

### Metrics Configuration

```bash
# Exporter: otlp, prometheus, console, none
OTEL_METRICS_EXPORTER=otlp

# Export interval (milliseconds)
OTEL_METRIC_EXPORT_INTERVAL=60000

# Export timeout (milliseconds)
OTEL_METRIC_EXPORT_TIMEOUT=30000
```

### Logs Configuration

```bash
# Exporter: otlp, console, none
OTEL_LOGS_EXPORTER=none

# Disable auto-instrumentation for logging (we use traditional logging)
OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=false
```

### Instrumentation Configuration

```bash
# Enable/disable auto-instrumentation
OTEL_PYTHON_DISABLED_INSTRUMENTATIONS=

# FastAPI instrumentation
OTEL_PYTHON_FASTAPI_EXCLUDED_URLS=/health,/metrics

# MongoDB instrumentation
OTEL_PYTHON_PYMONGO_CAPTURE_STATEMENT=true

# Redis instrumentation
OTEL_PYTHON_REDIS_CAPTURE_STATEMENT=true
```

### Resource Attributes

Add custom attributes to all telemetry:

```bash
# Deployment environment
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production,service.instance.id=app-1,k8s.pod.name=lablet-cloud-manager-abc123
```

### Development vs Production

**Development** (`.env.development`):

```bash
OTEL_SERVICE_NAME=lablet-cloud-manager
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=otlp
OTEL_LOGS_EXPORTER=none
OTEL_TRACES_SAMPLER=always_on
OTEL_LOG_LEVEL=debug
```

**Production** (`.env.production`):

```bash
OTEL_SERVICE_NAME=lablet-cloud-manager
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=otlp
OTEL_LOGS_EXPORTER=none
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1
OTEL_LOG_LEVEL=info
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production
```

## OTEL Collector Configuration

Edit `deployment/otel-collector-config.yaml` to configure the collector.

### Basic Configuration

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 1s
    send_batch_size: 1024

exporters:
  otlp/tempo:
    endpoint: tempo:4317
    tls:
      insecure: true

  prometheus:
    endpoint: "0.0.0.0:8889"

  logging:
    loglevel: debug

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/tempo, logging]

    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [prometheus, logging]
```

### Advanced Processors

#### Batch Processor

```yaml
processors:
  batch:
    # Time to wait before sending batch
    timeout: 10s

    # Number of items to batch before sending
    send_batch_size: 1024

    # Maximum batch size (hard limit)
    send_batch_max_size: 2048
```

#### Sampling Processor

```yaml
processors:
  # Probabilistic sampling (sample 10%)
  probabilistic_sampler:
    sampling_percentage: 10

  # Tail sampling (sample based on criteria)
  tail_sampling:
    decision_wait: 10s
    policies:
      # Always sample errors
      - name: error-policy
        type: status_code
        status_code:
          status_codes: [ERROR]

      # Sample slow requests
      - name: slow-traces
        type: latency
        latency:
          threshold_ms: 500

      # Sample 10% of everything else
      - name: probabilistic
        type: probabilistic
        probabilistic:
          sampling_percentage: 10
```

#### Attribute Processor

```yaml
processors:
  # Add attributes
  attributes:
    actions:
      - key: environment
        value: production
        action: insert

      - key: service.version
        value: 1.0.0
        action: insert

      # Remove sensitive attributes
      - key: user.email
        action: delete
```

#### Resource Processor

```yaml
processors:
  resource:
    attributes:
      - key: cloud.provider
        value: aws
        action: insert

      - key: cloud.region
        value: us-east-1
        action: insert
```

### Multiple Exporters

Export to multiple backends:

```yaml
exporters:
  # Tempo for traces
  otlp/tempo:
    endpoint: tempo:4317
    tls:
      insecure: true

  # Jaeger for traces (alternative)
  otlp/jaeger:
    endpoint: jaeger:4317
    tls:
      insecure: true

  # Datadog for traces
  datadog:
    api:
      key: ${DATADOG_API_KEY}

  # Prometheus for metrics
  prometheus:
    endpoint: "0.0.0.0:8889"

  # Remote write for metrics
  prometheusremotewrite:
    endpoint: http://prometheus-remote:9009/api/v1/write

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/tempo, datadog]  # Multiple exporters

    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [prometheus, prometheusremotewrite]
```

## Application Configuration

### Neuroglia Configuration

The application uses `Neuroglia.Observability` for auto-configuration:

```python
# src/main.py
from neuroglia.observability import Observability
from neuroglia.hosting.web import WebApplicationBuilder

def create_app() -> FastAPI:
    builder = WebApplicationBuilder(app_settings=app_settings)

    # Auto-configures OpenTelemetry from environment variables
    Observability.configure(builder)

    # Continue with other configuration...
    return builder.build()
```

**What it does**:

1. Reads `OTEL_*` environment variables
2. Configures OpenTelemetry SDK
3. Sets up trace and metric providers
4. Enables auto-instrumentation for:
   - FastAPI (HTTP requests/responses)
   - MongoDB (database queries)
   - Redis (cache operations)
5. Configures exporters (OTLP, Console, etc.)

### Manual Configuration (Advanced)

If you need more control, configure OpenTelemetry manually:

```python
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

# Configure tracer
trace_provider = TracerProvider(
    resource=Resource.create({
        "service.name": "lablet-cloud-manager",
        "service.version": "1.0.0",
    })
)
trace_provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(endpoint="http://otel-collector:4317")
    )
)
trace.set_tracer_provider(trace_provider)

# Configure meter
metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint="http://otel-collector:4317"),
    export_interval_millis=60000,
)
meter_provider = MeterProvider(
    resource=Resource.create({
        "service.name": "lablet-cloud-manager",
        "service.version": "1.0.0",
    }),
    metric_readers=[metric_reader],
)
metrics.set_meter_provider(meter_provider)
```

## Backend Configuration

### Tempo Configuration

Edit `docker-compose.yml` for Tempo settings:

```yaml
tempo:
  image: grafana/tempo:latest
  command: ["-config.file=/etc/tempo.yaml"]
  volumes:
    - ./deployment/tempo-config.yaml:/etc/tempo.yaml
  ports:
    - "4317"  # OTLP gRPC
```

**tempo-config.yaml** (basic):

```yaml
server:
  http_listen_port: 3200

distributor:
  receivers:
    otlp:
      protocols:
        grpc:

storage:
  trace:
    backend: local
    local:
      path: /tmp/tempo/traces

compactor:
  compaction:
    block_retention: 168h  # 7 days
```

### Prometheus Configuration

Edit `deployment/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  # Scrape OTEL Collector
  - job_name: 'otel-collector'
    static_configs:
      - targets: ['otel-collector:8889']

  # Scrape application directly (if using Prometheus exporter)
  - job_name: 'lablet-cloud-manager'
    static_configs:
      - targets: ['app:8000']
```

### Grafana Configuration

Configure data sources in `deployment/grafana/datasources.yml`:

```yaml
apiVersion: 1

datasources:
  # Tempo for traces
  - name: Tempo
    type: tempo
    access: proxy
    url: http://tempo:3200
    jsonData:
      httpMethod: GET
      tracesToLogs:
        datasourceUid: 'loki'
        tags: ['trace_id']

  # Prometheus for metrics
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    jsonData:
      httpMethod: POST
    isDefault: true
```

## Related Documentation

- [Observability Overview](./overview.md) - Concepts and introduction
- [Architecture](./architecture.md) - Technical architecture
- [Getting Started](./getting-started.md) - Quick start guide
- [Best Practices](./best-practices.md) - Configuration best practices

## Additional Resources

- [OpenTelemetry Configuration](https://opentelemetry.io/docs/concepts/sdk-configuration/)
- [OTEL Collector Configuration](https://opentelemetry.io/docs/collector/configuration/)
- [Grafana Datasources](https://grafana.com/docs/grafana/latest/datasources/)
