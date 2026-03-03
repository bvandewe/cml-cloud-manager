# Observability Troubleshooting

This guide covers common observability issues and their solutions.

## Table of Contents

- [Traces Not Appearing](#traces-not-appearing)
- [Metrics Not Recording](#metrics-not-recording)
- [High Memory Usage](#high-memory-usage)
- [Performance Issues](#performance-issues)
- [Configuration Problems](#configuration-problems)
- [Data Quality Issues](#data-quality-issues)

## Traces Not Appearing

### Symptom

Traces not visible in Grafana/Tempo after making API requests.

### Diagnosis

**1. Check if OTEL Collector is running**:

```bash
docker-compose ps otel-collector

# Should show: Up
```

**2. Check OTEL Collector logs**:

```bash
make logs-otel

# Or
docker-compose logs otel-collector
```

Look for errors like:

- `connection refused`
- `deadline exceeded`
- `failed to export`

**3. Check application can reach collector**:

```bash
# From host
curl http://localhost:4317

# From container
docker-compose exec app curl http://otel-collector:4317
```

**4. Verify environment variables**:

```bash
docker-compose exec app env | grep OTEL

# Should see:
# OTEL_TRACES_EXPORTER=otlp
# OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

**5. Check Tempo is receiving data**:

```bash
docker-compose logs otel-collector | grep -i tempo
```

### Solutions

**Problem**: Collector not running

```bash
# Start collector
docker-compose up -d otel-collector
```

**Problem**: Wrong endpoint

```bash
# Update .env
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

**Problem**: Traces disabled

```bash
# Update .env
OTEL_TRACES_EXPORTER=otlp  # Not 'none' or 'console'
```

**Problem**: Network issue

```bash
# Restart services
docker-compose restart app otel-collector tempo
```

**Problem**: Sampling rate too low

```bash
# Increase sampling
OTEL_TRACES_SAMPLER=always_on  # For development
```

### Verification

```bash
# Generate traffic
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"title":"Test","priority":"high"}'

# Check Grafana
open http://localhost:3000
# Navigate to Explore → Tempo → Search for "lablet-cloud-manager"
```

## Metrics Not Recording

### Symptom

Metrics not visible in Prometheus or Grafana.

### Diagnosis

**1. Check meter is initialized**:

```python
# In your code
from opentelemetry import metrics

meter = metrics.get_meter(__name__)
print(f"Meter: {meter}")  # Should not be None
```

**2. Check metrics are being called**:

```python
# Add debug logging
tasks_created.add(1, {"priority": "high"})
logger.debug("Recorded task creation metric")
```

**3. Check environment variable**:

```bash
echo $OTEL_METRICS_EXPORTER
# Should be: otlp
```

**4. Check Prometheus scraping collector**:

```bash
# Check if Prometheus is scraping OTEL Collector
curl http://localhost:8889/metrics

# Should see metrics like:
# lablet_cloud_manager_tasks_created_total{priority="high"} 5
```

**5. Check Prometheus targets**:

Open http://localhost:9090/targets

- Should show `otel-collector:8889` as UP

### Solutions

**Problem**: Meter not initialized

```python
# Ensure Observability is configured
from neuroglia.observability import Observability

builder = WebApplicationBuilder(app_settings=app_settings)
Observability.configure(builder)
```

**Problem**: Wrong exporter

```bash
# Update .env
OTEL_METRICS_EXPORTER=otlp  # Not 'none' or 'console'
```

**Problem**: Metrics not exported

```bash
# Check export interval
OTEL_METRIC_EXPORT_INTERVAL=60000  # 60 seconds

# For faster updates in development
OTEL_METRIC_EXPORT_INTERVAL=5000  # 5 seconds
```

**Problem**: Prometheus not scraping

```yaml
# Check deployment/prometheus.yml
scrape_configs:
  - job_name: 'otel-collector'
    static_configs:
      - targets: ['otel-collector:8889']  # Correct port
```

### Verification

```bash
# Query Prometheus directly
curl 'http://localhost:9090/api/v1/query?query=lablet_cloud_manager_tasks_created_total'

# Or use Grafana
open http://localhost:3000
# Navigate to Explore → Prometheus → Metrics Browser
```

## High Memory Usage

### Symptom

Application memory grows continuously or spikes.

### Diagnosis

**1. Check span attributes**:

Look for large attributes in your code:

```python
# ❌ Bad: Large attribute
span.set_attribute("task.data", json.dumps(large_object))  # 100KB!
```

**2. Check metric cardinality**:

```bash
# Check number of unique label combinations
curl http://localhost:8889/metrics | grep lablet_cloud_manager_tasks | wc -l
```

If > 1000 time series, you have high cardinality.

**3. Check for span leaks**:

```python
# ❌ Bad: Span never ends
span = tracer.start_span("operation")
# Missing span.end()!
```

**4. Monitor memory**:

```bash
# Check container memory
docker stats app

# Application memory
ps aux | grep python
```

### Solutions

**Problem**: Large span attributes

```python
# ❌ Bad
span.set_attribute("task.description", task.description)  # Could be 10KB

# ✅ Good: Truncate
description = task.description[:100] if task.description else ""
span.set_attribute("task.description_preview", description)
```

**Problem**: High metric cardinality

```python
# ❌ Bad: Unique IDs as labels
tasks_created.add(1, {"task_id": task_id})  # Millions of values!

# ✅ Good: Categorical labels
tasks_created.add(1, {"priority": "high", "status": "pending"})
```

**Problem**: Too many spans

```python
# ❌ Bad: Span per item
for item in items:  # 10,000 items
    with tracer.start_as_current_span("process_item"):
        process(item)

# ✅ Good: One span for batch
with tracer.start_as_current_span("process_items") as span:
    span.set_attribute("items.count", len(items))
    for item in items:
        process(item)
```

**Problem**: Batch size too large

```yaml
# In otel-collector-config.yaml
processors:
  batch:
    timeout: 1s
    send_batch_size: 512  # Reduce from 1024
```

**Problem**: Sampling rate too high

```bash
# Reduce sampling in production
OTEL_TRACES_SAMPLER=traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1  # 10% instead of 100%
```

## Performance Issues

### Symptom

Application is slower after adding observability.

### Diagnosis

**1. Measure overhead**:

```python
import time

# Without instrumentation
start = time.perf_counter()
result = await operation()
baseline = time.perf_counter() - start

# With instrumentation
start = time.perf_counter()
with tracer.start_as_current_span("operation"):
    result = await operation()
instrumented = time.perf_counter() - start

overhead = (instrumented - baseline) / baseline * 100
print(f"Overhead: {overhead:.2f}%")
```

**2. Check export blocking**:

```bash
# Check if exports are blocking
docker-compose logs app | grep -i "export"
```

**3. Profile the application**:

```bash
# Use py-spy to profile
pip install py-spy
py-spy top --pid $(pgrep -f "python.*main.py")
```

### Solutions

**Problem**: Synchronous exports (blocking)

OpenTelemetry SDK uses async exports by default. Verify:

```python
# Should use BatchSpanProcessor (async)
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Not SimpleSpanProcessor (blocking)
```

**Problem**: Too many spans

```python
# Reduce span granularity
# Only instrument significant operations (> 10ms)

# ❌ Bad: Span for trivial operation
with tracer.start_as_current_span("get_priority"):  # < 1ms
    priority = task.priority

# ✅ Good: No span for trivial operation
priority = task.priority
```

**Problem**: Large attributes

```python
# Limit attribute size
MAX_ATTR_SIZE = 1024  # 1KB

def set_safe_attribute(span, key, value):
    if isinstance(value, str) and len(value) > MAX_ATTR_SIZE:
        value = value[:MAX_ATTR_SIZE] + "..."
    span.set_attribute(key, value)
```

**Problem**: High export frequency

```bash
# Increase export interval
OTEL_METRIC_EXPORT_INTERVAL=60000  # 60 seconds instead of 5
```

## Configuration Problems

### Environment Variables Not Loaded

**Symptom**: Observability not working despite correct configuration.

**Solution**:

```bash
# Restart application after changing .env
docker-compose restart app

# Verify variables are loaded
docker-compose exec app env | grep OTEL
```

### Wrong Service Name

**Symptom**: Can't find traces/metrics for your service.

**Solution**:

```bash
# Check service name
echo $OTEL_SERVICE_NAME
# Should match what you search for in Grafana

# Update if wrong
OTEL_SERVICE_NAME=lablet-cloud-manager
```

### Collector Configuration Not Applied

**Symptom**: Collector changes not taking effect.

**Solution**:

```bash
# Restart collector after config changes
docker-compose restart otel-collector

# Check for syntax errors
docker-compose logs otel-collector | grep -i error
```

## Data Quality Issues

### Missing Span Attributes

**Problem**: Attributes not showing in Grafana/Tempo.

**Cause**: Attributes set after span ends.

**Solution**:

```python
# ❌ Bad: Attribute set after span ends
with tracer.start_as_current_span("operation") as span:
    result = do_work()
# Span ended here!
span.set_attribute("result", result)  # Too late!

# ✅ Good: Attribute set before span ends
with tracer.start_as_current_span("operation") as span:
    result = do_work()
    span.set_attribute("result", result)  # Within span scope
```

### Broken Trace Context

**Problem**: Spans appear as separate traces instead of one trace.

**Cause**: Context not propagated.

**Solution**:

```python
# ❌ Bad: Starting new trace
span = tracer.start_span("operation")  # No parent context!

# ✅ Good: Using current context
with tracer.start_as_current_span("operation") as span:
    ...
```

For async operations:

```python
# ❌ Bad: Context lost in background task
async def handler():
    with tracer.start_as_current_span("parent"):
        asyncio.create_task(background_work())  # Context lost!

# ✅ Good: Pass context explicitly
from opentelemetry import context

async def handler():
    with tracer.start_as_current_span("parent"):
        ctx = context.get_current()
        asyncio.create_task(background_work(ctx))

async def background_work(ctx):
    with tracer.start_as_current_span("background", context=ctx):
        ...
```

### Metrics Not Aggregating

**Problem**: Seeing duplicate metrics instead of aggregated values.

**Cause**: Inconsistent label names or values.

**Solution**:

```python
# ❌ Bad: Inconsistent labels
tasks_created.add(1, {"priority": "HIGH"})
tasks_created.add(1, {"priority": "high"})  # Different value!
tasks_created.add(1, {"prio": "high"})      # Different key!

# ✅ Good: Consistent labels
tasks_created.add(1, {"priority": "high"})
tasks_created.add(1, {"priority": "high"})  # Same key and value
```

## Getting Help

### Debug Mode

Enable verbose logging:

```bash
# In .env
OTEL_LOG_LEVEL=debug
OTEL_TRACES_EXPORTER=console,otlp  # Export to both console and collector
```

Check application logs:

```bash
make logs-app
```

### Collector Debug

Enable debug logging in collector:

```yaml
# otel-collector-config.yaml
exporters:
  logging:
    loglevel: debug  # Change from 'info'

service:
  pipelines:
    traces:
      exporters: [otlp/tempo, logging]  # Add logging exporter
```

### Test Configuration

Use minimal config to isolate issues:

```bash
# Minimal .env for testing
OTEL_SERVICE_NAME=lablet-cloud-manager
OTEL_TRACES_EXPORTER=console
OTEL_METRICS_EXPORTER=console

# Run app and check logs
make logs-app
```

### Useful Commands

```bash
# Check all services
docker-compose ps

# View all logs
docker-compose logs -f

# Check specific service
docker-compose logs otel-collector
docker-compose logs tempo
docker-compose logs prometheus

# Restart everything
docker-compose restart

# Clean restart
docker-compose down
docker-compose up -d
```

## Related Documentation

- [Observability Overview](./overview.md) - Concepts and introduction
- [Configuration](./configuration.md) - Configuration options
- [Getting Started](./getting-started.md) - Quick start guide
- [Architecture](./architecture.md) - Technical architecture

## Additional Resources

- [OpenTelemetry Troubleshooting](https://opentelemetry.io/docs/concepts/signals/)
- [OTEL Collector Troubleshooting](https://opentelemetry.io/docs/collector/troubleshooting/)
- [Grafana Tempo Troubleshooting](https://grafana.com/docs/tempo/latest/troubleshooting/)
