# Getting Started with Observability

This guide provides a quick start to using observability features in the Cml Cloud Manager.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Viewing Traces](#viewing-traces)
- [Viewing Metrics](#viewing-metrics)
- [Example Workflows](#example-workflows)

## Prerequisites

1. **Docker Compose** - Running OTEL Collector, Tempo, and Prometheus
2. **Poetry** - Python dependency management
3. **Running Application** - Cml Cloud Manager must be running

## Quick Start

### 1. Start Observability Stack

```bash
# Start all services including OTEL Collector, Tempo, and Prometheus
make up

# Or start specific services
docker-compose up -d otel-collector tempo prometheus grafana
```

### 2. Verify Services

```bash
# Check OTEL Collector logs
make logs-otel

# Check if services are running
docker-compose ps
```

**Expected Output**:

```
NAME                STATUS    PORTS
otel-collector      Up        0.0.0.0:4317->4317/tcp
tempo               Up
prometheus          Up        0.0.0.0:9090->9090/tcp
grafana             Up        0.0.0.0:3000->3000/tcp
```

### 3. Access Web UIs

Open the following URLs in your browser:

- **Grafana**: http://localhost:3000
  - Default credentials: `admin` / `admin`
  - Used for viewing traces (Tempo) and metrics (Prometheus)

- **Prometheus**: http://localhost:9090
  - Direct access to metrics
  - Execute PromQL queries

### 4. Generate Telemetry

Make API requests to generate traces and metrics:

```bash
# Create a task (generates trace and metrics)
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "title": "Test Task",
    "description": "Testing observability",
    "priority": "high"
  }'

# List tasks
curl -X GET http://localhost:8000/api/tasks \
  -H "Authorization: Bearer YOUR_TOKEN"

# Update a task
curl -X PUT http://localhost:8000/api/tasks/{task_id} \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "title": "Updated Task",
    "status": "in_progress"
  }'
```

## Viewing Traces

### In Grafana (Recommended)

1. **Open Grafana**: http://localhost:3000

2. **Navigate to Explore**:
   - Click on the **Explore** icon (compass) in the left sidebar

3. **Select Tempo Data Source**:
   - In the dropdown at the top, select **Tempo**

4. **Search for Traces**:
   - **Search** tab: Search by service name
     - Service Name: `lablet-cloud-manager`
     - Click **Run Query**

   - **TraceQL** tab: Use TraceQL queries

     ```traceql
     { service.name="lablet-cloud-manager" && http.status_code=200 }
     ```

5. **View Trace Details**:
   - Click on any trace in the results
   - Explore the span hierarchy
   - Check span attributes and timing

### Example: Task Creation Trace

When you create a task, you'll see a trace like this:

```
lablet-cloud-manager: POST /api/tasks (200ms)
├─ create_task_entity (15ms)
│  ├─ span: validate input (3ms)
│  └─ span: create domain object (12ms)
├─ motor_task_repository.add (150ms)
│  ├─ pymongo.insert_one (140ms)
│  │  Attributes:
│  │  ├─ db.system: mongodb
│  │  ├─ db.operation: insert
│  │  └─ db.collection: tasks
│  └─ publish_domain_events (10ms)
└─ record_metrics (5ms)
```

**What to Look For**:

- **Duration**: Total and per-span timing
- **Attributes**: Task ID, priority, status, user ID
- **Events**: Milestones within spans
- **Errors**: Exceptions and error status

## Viewing Metrics

### In Prometheus

1. **Open Prometheus**: http://localhost:9090

2. **Execute Queries**:
   - Click on **Graph** tab
   - Enter a PromQL query
   - Click **Execute**

**Example Queries**:

```promql
# Task creation rate (per second)
rate(lablet_cloud_manager_tasks_created_total[5m])

# Total tasks created
lablet_cloud_manager_tasks_created_total

# Task processing time (95th percentile)
histogram_quantile(0.95, rate(lablet_cloud_manager_task_processing_time_bucket[5m]))

# Tasks by priority
sum by (priority) (lablet_cloud_manager_tasks_created_total)
```

### In Grafana

1. **Open Grafana**: http://localhost:3000

2. **Navigate to Explore**:
   - Select **Prometheus** data source

3. **Build Queries**:
   - Use the **Metrics Browser** or write PromQL
   - Visualize as Table or Graph

4. **Create Dashboards** (Optional):
   - Click **+** → **Dashboard**
   - Add panels with metric queries
   - Save dashboard

## Example Workflows

### Workflow 1: Debug a Slow Request

**Scenario**: API endpoint is slow

**Steps**:

1. **Identify slow traces** in Grafana/Tempo:

   ```traceql
   { service.name="lablet-cloud-manager" && duration > 500ms }
   ```

2. **Analyze the trace**:
   - Find the slowest span
   - Check database queries
   - Look for N+1 queries

3. **Check metrics** for patterns:

   ```promql
   # Response time trend
   histogram_quantile(0.95, rate(http_server_duration_bucket[5m]))
   ```

4. **Fix the issue**:
   - Add database indexes
   - Optimize queries
   - Implement caching

### Workflow 2: Monitor Task Creation

**Scenario**: Track task creation rate

**Steps**:

1. **Query task creation rate**:

   ```promql
   rate(lablet_cloud_manager_tasks_created_total[5m])
   ```

2. **Visualize in Grafana**:
   - Create a graph panel
   - Group by priority:

     ```promql
     sum by (priority) (rate(lablet_cloud_manager_tasks_created_total[5m]))
     ```

3. **Set up alerts**:
   - Create alert rule
   - Threshold: `< 1` (less than 1 task/sec)
   - Notification channel

### Workflow 3: Root Cause Analysis

**Scenario**: Production error reported

**Steps**:

1. **Check application logs**:

   ```bash
   make logs-app
   ```

   - Find error message
   - Copy **trace ID** from log

2. **Find trace in Grafana/Tempo**:
   - Paste trace ID in search
   - View full trace

3. **Analyze failure**:
   - Identify failed span
   - Check error attributes
   - Review span events

4. **Correlate with metrics**:

   ```promql
   # Error rate spike?
   rate(lablet_cloud_manager_tasks_failed_total[5m])
   ```

5. **Check context**:
   - Span attributes: user ID, task ID, priority
   - Timing: when did it start failing?
   - Pattern: specific user/task type?

### Workflow 4: Performance Optimization

**Scenario**: Optimize task processing

**Steps**:

1. **Baseline metrics**:

   ```promql
   histogram_quantile(0.95, rate(lablet_cloud_manager_task_processing_time_bucket[5m]))
   ```

2. **Generate test load**:

   ```bash
   # Create multiple tasks
   for i in {1..100}; do
     curl -X POST http://localhost:8000/api/tasks \
       -H "Content-Type: application/json" \
       -H "Authorization: Bearer $TOKEN" \
       -d "{\"title\":\"Task $i\",\"priority\":\"high\"}"
   done
   ```

3. **Analyze traces**:
   - Find common slow patterns
   - Identify bottlenecks

4. **Implement optimizations**:
   - Add indexes
   - Use batch operations
   - Optimize queries

5. **Measure improvement**:

   ```promql
   # Before vs after
   histogram_quantile(0.95, rate(lablet_cloud_manager_task_processing_time_bucket[5m]))
   ```

## Next Steps

- **[Metrics Guide](./metrics.md)**: Learn to add custom metrics
- **[Tracing Guide](./tracing.md)**: Learn to add custom spans
- **[Configuration](./configuration.md)**: Configure observability settings
- **[Best Practices](./best-practices.md)**: Follow observability best practices
- **[Troubleshooting](./troubleshooting.md)**: Solve common issues

## Tips and Tricks

### Enable Verbose Logging

For debugging observability issues:

```bash
# Add to .env
OTEL_LOG_LEVEL=debug
```

### View Raw Telemetry

Check OTEL Collector logs:

```bash
make logs-otel

# Or filter for specific data
docker-compose logs otel-collector | grep "Trace"
docker-compose logs otel-collector | grep "Metric"
```

### Test Without Backend

Use console exporter for development:

```bash
# In .env
OTEL_TRACES_EXPORTER=console
OTEL_METRICS_EXPORTER=console
```

Telemetry will be printed to application logs:

```bash
make logs-app
```

## Related Documentation

- [Observability Overview](./overview.md) - Concepts and introduction
- [Architecture](./architecture.md) - Technical architecture
- [Configuration](./configuration.md) - Detailed configuration
- [Troubleshooting](./troubleshooting.md) - Common issues

## Additional Resources

- [Grafana Getting Started](https://grafana.com/docs/grafana/latest/getting-started/)
- [Prometheus Querying Basics](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [TraceQL Documentation](https://grafana.com/docs/tempo/latest/traceql/)
