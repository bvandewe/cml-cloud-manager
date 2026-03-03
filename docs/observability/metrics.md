# Metrics Instrumentation Guide

This guide covers how to implement metrics instrumentation in the Cml Cloud Manager using OpenTelemetry.

## Table of Contents

- [Overview](#overview)
- [Metric Types](#metric-types)
- [Implementation](#implementation)
- [Best Practices](#best-practices)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

## Overview

**Metrics** are numerical measurements aggregated over time that help you understand system behavior and performance.

### When to Use Metrics

Use metrics for:

- ✅ **Counting events**: Tasks created, API requests, errors
- ✅ **Measuring rates**: Requests per second, throughput
- ✅ **Tracking distributions**: Response times, payload sizes
- ✅ **Monitoring resources**: CPU usage, memory, database connections
- ✅ **Alerting**: Trigger alerts when values cross thresholds

Don't use metrics for:

- ❌ High-cardinality data (unique user IDs, session IDs)
- ❌ Debugging individual requests (use traces)
- ❌ Storing events (use logs)

### Architecture

```mermaid
graph LR
    Code[Application Code]
    Meter[OpenTelemetry Meter]
    Instruments[Metric Instruments]
    Reader[Metric Reader]
    Exporter[OTLP Exporter]
    Collector[OTEL Collector]
    Backend[Backend: Prometheus]

    Code -->|Create| Meter
    Meter -->|Create| Instruments
    Instruments -->|Record| Reader
    Reader -->|Export| Exporter
    Exporter -->|Send| Collector
    Collector -->|Forward| Backend

    style Code fill:#4CAF50
    style Instruments fill:#2196F3
    style Collector fill:#FF9800
```

## Metric Types

OpenTelemetry provides several metric instruments, each for different use cases:

### 1. Counter

**What**: Monotonically increasing value (only goes up).

**When**: Counting events that accumulate over time.

**Examples**:

- Total tasks created
- Total API requests
- Total errors

**API**:

```python
from opentelemetry import metrics

meter = metrics.get_meter(__name__)

# Create counter
tasks_created = meter.create_counter(
    name="lablet_cloud_manager.tasks.created",
    description="Total tasks created",
    unit="1"
)

# Record value (always positive)
tasks_created.add(1, {"priority": "high", "status": "pending"})
```

**Visualization**: Use `rate()` or `increase()` to see rate of change.

```promql
# Tasks created per second
rate(lablet_cloud_manager_tasks_created_total[5m])

# Total tasks created in last hour
increase(lablet_cloud_manager_tasks_created_total[1h])
```

### 2. UpDownCounter

**What**: Value that can increase or decrease.

**When**: Tracking values that go up and down.

**Examples**:

- Active connections
- Queue length
- Number of items in cache

**API**:

```python
active_tasks = meter.create_up_down_counter(
    name="lablet_cloud_manager.tasks.active",
    description="Number of active (non-completed) tasks",
    unit="1"
)

# Increase
active_tasks.add(1, {"department": "engineering"})

# Decrease
active_tasks.add(-1, {"department": "engineering"})
```

**Visualization**: Use directly to see current count.

```promql
# Current active tasks
lablet_cloud_manager_tasks_active

# Average active tasks over time
avg_over_time(lablet_cloud_manager_tasks_active[5m])
```

### 3. Histogram

**What**: Distribution of values over time.

**When**: Measuring latency, size, or any value you want to analyze statistically.

**Examples**:

- Request duration
- Payload size
- Database query time

**API**:

```python
task_processing_time = meter.create_histogram(
    name="lablet_cloud_manager.task.processing_time",
    description="Time to process tasks",
    unit="ms"
)

# Record observation
processing_time_ms = (time.time() - start_time) * 1000
task_processing_time.record(
    processing_time_ms,
    {"operation": "create", "priority": "high"}
)
```

**Visualization**: Use percentiles, averages, histograms.

```promql
# 95th percentile processing time
histogram_quantile(0.95,
  rate(lablet_cloud_manager_task_processing_time_bucket[5m]))

# Average processing time
rate(lablet_cloud_manager_task_processing_time_sum[5m]) /
rate(lablet_cloud_manager_task_processing_time_count[5m])
```

### 4. Gauge (Observable)

**What**: Current value at a point in time.

**When**: Measuring instantaneous values from external sources.

**Examples**:

- Current memory usage
- Database connection pool size
- Queue depth

**API**:

```python
def get_memory_usage():
    """Callback that returns current memory usage."""
    import psutil
    return psutil.Process().memory_info().rss / 1024 / 1024  # MB

# Create observable gauge
meter.create_observable_gauge(
    name="lablet_cloud_manager.memory.usage",
    description="Current memory usage",
    unit="MB",
    callbacks=[get_memory_usage]
)
```

**Note**: Callback is invoked periodically by the SDK.

### Comparison Table

| Type | Direction | Use Case | Example |
|------|-----------|----------|---------|
| **Counter** | Up only | Cumulative events | Total requests |
| **UpDownCounter** | Up/Down | Current count | Active connections |
| **Histogram** | Observations | Value distributions | Request latency |
| **Gauge** | Current value | Instantaneous reading | Memory usage |

## Implementation

### Step 1: Get a Meter

Create a meter for your module:

```python
# src/observability/metrics.py or in your module
from opentelemetry import metrics

# One meter per module/component
meter = metrics.get_meter(__name__)
```

**Best Practice**: Use `__name__` to namespace your metrics by module.

### Step 2: Create Metric Instruments

Define instruments at module level (not in functions):

```python
# src/observability/metrics.py
from opentelemetry import metrics

meter = metrics.get_meter(__name__)

# Counters
tasks_created = meter.create_counter(
    name="lablet_cloud_manager.tasks.created",
    description="Total tasks created",
    unit="1"
)

tasks_completed = meter.create_counter(
    name="lablet_cloud_manager.tasks.completed",
    description="Total tasks completed",
    unit="1"
)

tasks_failed = meter.create_counter(
    name="lablet_cloud_manager.tasks.failed",
    description="Total task failures",
    unit="1"
)

# Histograms
task_processing_time = meter.create_histogram(
    name="lablet_cloud_manager.task.processing_time",
    description="Time to process tasks",
    unit="ms"
)
```

**Why module level?**

- Instruments are lightweight
- Create once, use many times
- Better performance

### Step 3: Record Measurements

Import and use instruments in your code:

```python
# src/application/commands/create_task_command.py
import time
from observability.metrics import tasks_created, task_processing_time

class CreateTaskCommandHandler:
    async def handle_async(self, command: CreateTaskCommand):
        start_time = time.time()

        # Business logic
        task = await self.create_task(command)

        # Record metrics
        processing_time_ms = (time.time() - start_time) * 1000

        tasks_created.add(
            1,
            {
                "priority": task.priority.value,
                "status": task.status.value,
                "has_assignee": bool(task.assignee_id),
            }
        )

        task_processing_time.record(
            processing_time_ms,
            {"operation": "create", "priority": task.priority.value}
        )

        return task
```

### Step 4: Add Attributes (Labels)

Attributes provide dimensions for filtering and grouping:

```python
# Good: Low-cardinality attributes
tasks_created.add(1, {
    "priority": "high",        # 3 values: high, medium, low
    "status": "pending",       # 4 values: pending, in_progress, completed, failed
    "department": "engineering" # ~10 values
})

# Bad: High-cardinality attributes
tasks_created.add(1, {
    "task_id": "uuid-1234",    # ❌ Millions of unique values!
    "user_id": "user-5678",    # ❌ Thousands of unique values!
})
```

**Why avoid high cardinality?**

- Explodes storage costs
- Slows down queries
- Metrics backends charge per unique series

### Step 5: Configure Export

Metrics are automatically exported via OpenTelemetry SDK configured in `main.py`:

```python
# src/main.py
from neuroglia.observability import Observability

def create_app() -> FastAPI:
    builder = WebApplicationBuilder(app_settings=app_settings)

    # Auto-configures metrics export
    Observability.configure(builder)
```

**Configuration** (via environment variables):

```bash
# Export to OTEL Collector
OTEL_METRICS_EXPORTER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317

# Or export to console (development)
OTEL_METRICS_EXPORTER=console
```

## Best Practices

### 1. Naming Conventions

Follow OpenTelemetry semantic conventions:

**Format**: `{namespace}.{component}.{metric_name}`

```python
# Good examples
"lablet_cloud_manager.tasks.created"           # namespace.component.metric
"lablet_cloud_manager.task.processing_time"
"lablet_cloud_manager.database.queries"
"lablet_cloud_manager.cache.hits"

# Bad examples
"TasksCreated"                        # No namespace, capitalized
"tasks"                               # Too vague
"lablet_cloud_manager_tasks_created_total"     # Wrong separator (use dots)
```

**Units**: Use standard units

```python
# Time
unit="ms"        # milliseconds
unit="s"         # seconds

# Size
unit="By"        # bytes
unit="MB"        # megabytes

# Count
unit="1"         # dimensionless count
unit="{items}"   # count of items

# Percentage
unit="%"         # percentage (0-100)
```

### 2. Instrument Naming

Be descriptive and consistent:

```python
# Counters: Use noun (what is being counted)
tasks_created = meter.create_counter("lablet_cloud_manager.tasks.created")
requests_failed = meter.create_counter("lablet_cloud_manager.requests.failed")

# Histograms: Use noun describing measured value
request_duration = meter.create_histogram("lablet_cloud_manager.request.duration")
payload_size = meter.create_histogram("lablet_cloud_manager.payload.size")
```

### 3. Attribute Design

**Use categorical attributes**:

```python
# Good: Limited set of values
{
    "priority": "high",          # 3 values
    "status": "completed",       # 4 values
    "operation": "create",       # CRUD operations
    "error_type": "validation",  # ~10 error types
}

# Bad: Unique values
{
    "task_id": "uuid",           # Millions
    "user_email": "user@...",    # Thousands
    "timestamp": "2024-...",     # Infinite
}
```

**Keep attribute count low**:

```python
# Good: 2-4 attributes
tasks_created.add(1, {"priority": "high", "status": "pending"})

# Bad: Too many attributes
tasks_created.add(1, {
    "priority": "high",
    "status": "pending",
    "department": "eng",
    "assignee": "john",
    "created_by": "admin",
    "project": "alpha",
    # ... 10 more attributes
})
```

**Cardinality calculation**:

```
Total series = attribute1_values × attribute2_values × ... × attributeN_values

Example:
priority (3) × status (4) × department (10) = 120 series ✅

vs.

priority (3) × user_id (10,000) = 30,000 series ❌
```

### 4. Recording Patterns

**Pattern 1: Increment Counter**

```python
# Simple increment
tasks_created.add(1)

# With attributes
tasks_created.add(1, {"priority": "high"})

# Conditional increment
if task.priority == TaskPriority.HIGH:
    high_priority_tasks.add(1)
```

**Pattern 2: Timing Operations**

```python
import time

start_time = time.time()

# Perform operation
result = await perform_operation()

# Record duration
duration_ms = (time.time() - start_time) * 1000
operation_duration.record(duration_ms, {"operation": "process"})
```

**Pattern 3: Context Manager**

```python
import time
from contextlib import contextmanager

@contextmanager
def record_duration(histogram, attributes):
    start_time = time.time()
    try:
        yield
    finally:
        duration_ms = (time.time() - start_time) * 1000
        histogram.record(duration_ms, attributes)

# Usage
with record_duration(task_processing_time, {"operation": "create"}):
    await create_task(command)
```

**Pattern 4: Decorator**

```python
def record_execution_time(operation: str):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                task_processing_time.record(
                    duration_ms,
                    {"operation": operation, "status": "success"}
                )
                return result
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                task_processing_time.record(
                    duration_ms,
                    {"operation": operation, "status": "error"}
                )
                raise
        return wrapper
    return decorator

# Usage
@record_execution_time("create_task")
async def create_task(command):
    ...
```

### 5. Error Handling

Always record success and failure:

```python
try:
    result = await perform_operation()
    operations_successful.add(1, {"operation": "process"})
except ValidationError as e:
    operations_failed.add(1, {"operation": "process", "error": "validation"})
    raise
except Exception as e:
    operations_failed.add(1, {"operation": "process", "error": "unknown"})
    raise
```

### 6. Performance Considerations

**Metrics are lightweight**:

- Recording metrics is fast (microseconds)
- Aggregation happens asynchronously
- Export is batched

**But avoid**:

- Recording in tight loops (aggregate first)
- Creating instruments dynamically
- Excessive attribute counts

```python
# Bad: Recording in loop
for item in items:
    items_processed.add(1)  # 1000 calls

# Good: Aggregate first
items_processed.add(len(items))  # 1 call
```

## Examples

### Example 1: Task Creation Metrics

Full instrumentation of task creation:

```python
# src/observability/metrics.py
from opentelemetry import metrics

meter = metrics.get_meter(__name__)

tasks_created = meter.create_counter(
    name="lablet_cloud_manager.tasks.created",
    description="Total tasks created",
    unit="1"
)

task_processing_time = meter.create_histogram(
    name="lablet_cloud_manager.task.processing_time",
    description="Time to process task operations",
    unit="ms"
)
```

```python
# src/application/commands/create_task_command.py
import time
from observability.metrics import tasks_created, task_processing_time
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

class CreateTaskCommandHandler:
    async def handle_async(
        self,
        command: CreateTaskCommand
    ) -> OperationResult[Task]:
        start_time = time.time()

        try:
            # Create task entity
            with tracer.start_as_current_span("create_task_entity") as span:
                task = Task(
                    title=command.title,
                    description=command.description,
                    priority=TaskPriority(command.priority),
                    status=TaskStatus(command.status),
                    assignee_id=command.assignee_id,
                    department=command.department,
                )
                span.set_attribute("task.priority", task.priority.value)
                span.set_attribute("task.status", task.status.value)

            # Save to repository
            saved_task = await self.task_repository.add_async(task)

            # Record metrics
            processing_time_ms = (time.time() - start_time) * 1000

            tasks_created.add(
                1,
                {
                    "priority": saved_task.state.priority.value,
                    "status": saved_task.state.status.value,
                    "has_assignee": bool(saved_task.state.assignee_id),
                    "has_department": bool(saved_task.state.department),
                }
            )

            task_processing_time.record(
                processing_time_ms,
                {"operation": "create", "priority": saved_task.state.priority.value}
            )

            return OperationResult.success(saved_task)

        except Exception as e:
            processing_time_ms = (time.time() - start_time) * 1000
            task_processing_time.record(
                processing_time_ms,
                {"operation": "create", "status": "error"}
            )
            raise
```

### Example 2: API Request Metrics

Track API endpoint usage:

```python
# src/observability/metrics.py
api_requests = meter.create_counter(
    name="lablet_cloud_manager.api.requests",
    description="Total API requests",
    unit="1"
)

api_request_duration = meter.create_histogram(
    name="lablet_cloud_manager.api.request.duration",
    description="API request duration",
    unit="ms"
)
```

```python
# src/api/middleware.py
from fastapi import Request
import time
from observability.metrics import api_requests, api_request_duration

async def metrics_middleware(request: Request, call_next):
    start_time = time.time()

    # Process request
    response = await call_next(request)

    # Record metrics
    duration_ms = (time.time() - start_time) * 1000

    api_requests.add(
        1,
        {
            "method": request.method,
            "endpoint": request.url.path,
            "status_code": response.status_code,
        }
    )

    api_request_duration.record(
        duration_ms,
        {
            "method": request.method,
            "endpoint": request.url.path,
        }
    )

    return response
```

### Example 3: Database Query Metrics

Monitor database performance:

```python
# src/observability/metrics.py
db_queries = meter.create_counter(
    name="lablet_cloud_manager.database.queries",
    description="Total database queries",
    unit="1"
)

db_query_duration = meter.create_histogram(
    name="lablet_cloud_manager.database.query.duration",
    description="Database query duration",
    unit="ms"
)
```

```python
# src/integration/repositories/motor_task_repository.py
import time
from observability.metrics import db_queries, db_query_duration

class MongoTaskRepository(TaskRepository):
    async def get_by_id_async(self, id: str) -> Task | None:
        start_time = time.time()

        try:
            result = await self._collection.find_one({"_id": id})

            duration_ms = (time.time() - start_time) * 1000
            db_queries.add(1, {"operation": "find_one", "collection": "tasks"})
            db_query_duration.record(
                duration_ms,
                {"operation": "find_one"}
            )

            return self._deserialize(result) if result else None

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            db_queries.add(
                1,
                {"operation": "find_one", "collection": "tasks", "status": "error"}
            )
            db_query_duration.record(
                duration_ms,
                {"operation": "find_one", "status": "error"}
            )
            raise
```

### Example 4: Business Metrics

Track business-critical metrics:

```python
# src/observability/metrics.py
tasks_by_department = meter.create_counter(
    name="lablet_cloud_manager.tasks.by_department",
    description="Tasks created by department",
    unit="1"
)

high_priority_tasks = meter.create_up_down_counter(
    name="lablet_cloud_manager.tasks.high_priority.active",
    description="Active high-priority tasks",
    unit="1"
)

task_completion_rate = meter.create_histogram(
    name="lablet_cloud_manager.task.completion_time",
    description="Time from creation to completion",
    unit="hours"
)
```

```python
# Usage in handlers
tasks_by_department.add(1, {"department": task.department})

# When task is created
if task.priority == TaskPriority.HIGH:
    high_priority_tasks.add(1)

# When task is completed
if task.priority == TaskPriority.HIGH:
    high_priority_tasks.add(-1)

# Record completion time
completion_hours = (task.completed_at - task.created_at).total_seconds() / 3600
task_completion_rate.record(completion_hours, {"priority": task.priority.value})
```

## Troubleshooting

### Metrics Not Appearing

**1. Check exporter configuration**:

```bash
# Should be 'otlp' or 'console'
echo $OTEL_METRICS_EXPORTER

# Should be set
echo $OTEL_EXPORTER_OTLP_ENDPOINT
```

**2. Check collector is receiving metrics**:

```bash
# View collector logs
docker-compose logs otel-collector | grep metrics

# Should see: "Metric {...}"
```

**3. Add debug logging**:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

tasks_created.add(1, {"priority": "high"})
print("Metric recorded")
```

### High Cardinality Issues

**Symptoms**:

- Slow queries
- High memory usage
- Storage costs increasing

**Solution**:

```python
# Before: High cardinality
tasks_created.add(1, {
    "task_id": task.id,        # ❌ Millions of values
    "user_email": user.email,  # ❌ Thousands of values
})

# After: Low cardinality
tasks_created.add(1, {
    "priority": task.priority.value,  # ✅ 3 values
    "department": task.department,     # ✅ ~10 values
})
```

### Metrics Not Aggregating

**Problem**: Seeing raw observations instead of aggregated metrics.

**Cause**: Using histogram for counting or counter for distributions.

**Solution**:

```python
# Wrong: Using histogram for counting
task_count.record(1)  # ❌

# Right: Use counter for counting
tasks_created.add(1)  # ✅

# Wrong: Using counter for latency
request_time.add(123)  # ❌

# Right: Use histogram for latency
request_duration.record(123)  # ✅
```

## Related Documentation

- [Observability Overview](./overview.md) - Observability architecture
- [Tracing Guide](./tracing.md) - Distributed tracing
- [Architecture Overview](../architecture/overview.md) - System architecture

## Additional Resources

- [OpenTelemetry Metrics Specification](https://opentelemetry.io/docs/specs/otel/metrics/)
- [Metrics API Reference](https://opentelemetry-python.readthedocs.io/en/latest/api/metrics.html)
- [Prometheus Best Practices](https://prometheus.io/docs/practices/naming/)
