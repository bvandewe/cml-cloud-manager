# Observability Best Practices

This guide covers best practices for implementing observability in the Cml Cloud Manager.

## Table of Contents

- [Naming Conventions](#naming-conventions)
- [Cardinality Control](#cardinality-control)
- [Span Management](#span-management)
- [Error Handling](#error-handling)
- [Sampling Strategies](#sampling-strategies)
- [Cost Management](#cost-management)
- [Security](#security)
- [Performance](#performance)

## Naming Conventions

### Metrics Naming

Use consistent, hierarchical naming:

**Format**: `{namespace}.{component}.{metric_name}`

```python
# ✅ Good: Clear hierarchy
meter.create_counter("lablet_cloud_manager.tasks.created")
meter.create_counter("lablet_cloud_manager.tasks.completed")
meter.create_counter("lablet_cloud_manager.tasks.failed")
meter.create_histogram("lablet_cloud_manager.task.processing_time")

# ❌ Bad: Inconsistent naming
meter.create_counter("TasksCreated")
meter.create_counter("task_complete")
meter.create_histogram("ProcessTime")
```

**Conventions**:

- Use lowercase with underscores
- Start with application/service name
- Group related metrics with common prefix
- Use descriptive, unambiguous names
- Include units in name or description

### Span Naming

Use descriptive, operation-focused names:

**Format**: `{operation_name}` (lowercase with underscores)

```python
# ✅ Good: Describes operation
with tracer.start_as_current_span("create_task_entity"):
    ...

with tracer.start_as_current_span("validate_task_input"):
    ...

# ❌ Bad: Too generic or vague
with tracer.start_as_current_span("process"):
    ...

with tracer.start_as_current_span("do_work"):
    ...
```

**Conventions**:

- Use verb + noun format
- Be specific about the operation
- Keep names concise (< 50 characters)
- Avoid dynamic values in span names

### Attribute Naming

Use dot notation for namespacing:

```python
# ✅ Good: Namespaced attributes
span.set_attribute("task.id", task_id)
span.set_attribute("task.priority", "high")
span.set_attribute("task.status", "pending")
span.set_attribute("user.id", user_id)
span.set_attribute("user.role", "admin")

# ❌ Bad: Flat namespace
span.set_attribute("taskId", task_id)
span.set_attribute("priority", "high")
span.set_attribute("id", user_id)
```

**Conventions**:

- Follow [OpenTelemetry Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/)
- Use lowercase with dots
- Group related attributes
- Prefix custom attributes with domain (e.g., `task.`, `user.`)

## Cardinality Control

**Cardinality** = number of unique combinations of label values.

### High Cardinality Problem

**❌ Bad: Unbounded cardinality**

```python
# Don't use unique IDs as metric labels
tasks_created.add(1, {
    "task_id": task_id,  # Millions of unique values!
    "user_id": user_id   # Thousands of unique values!
})
```

**Why it's bad**:

- Explodes storage costs
- Slows down queries
- May hit backend limits
- Creates millions of time series

### Low Cardinality Solution

**✅ Good: Bounded cardinality**

```python
# Use categorical values
tasks_created.add(1, {
    "priority": "high",      # 3 values: low, medium, high
    "status": "pending",     # 4 values: pending, in_progress, completed, failed
    "department": "engineering"  # ~10 values
})
```

**Guidelines**:

- Limit to < 10 unique values per label
- Use categories, not IDs
- Prefer enums over strings
- Document expected cardinality

### Span Attributes (Different Rules)

Spans can have high-cardinality attributes:

```python
# ✅ OK for spans: Include IDs and detailed context
with tracer.start_as_current_span("update_task") as span:
    span.set_attribute("task.id", task_id)  # OK: Spans are sampled
    span.set_attribute("user.id", user_id)
    span.set_attribute("request.id", request_id)
```

**Why it's OK**:

- Traces are sampled (not all stored)
- Individual traces are cheap
- IDs needed for correlation

## Span Management

### When to Create Spans

**✅ Create spans for**:

- Significant operations (> 10ms)
- External calls (DB, API, cache)
- Business operations (create task, send email)
- Error-prone operations

**❌ Don't create spans for**:

- Trivial operations (< 1ms)
- Simple getters/setters
- Pure functions without I/O
- High-frequency loops (> 1000/sec)

### Span Hierarchy

Create meaningful hierarchies:

```python
# ✅ Good: Logical hierarchy
async def create_task(command: CreateTaskCommand):
    with tracer.start_as_current_span("create_task") as span:
        # Child span: Validation
        with tracer.start_as_current_span("validate_input"):
            validate(command)

        # Child span: Business logic
        with tracer.start_as_current_span("create_entity"):
            task = Task(...)

        # Child span: Persistence (auto-instrumented)
        await repository.save(task)

        # Child span: Side effects
        with tracer.start_as_current_span("publish_events"):
            await event_bus.publish(task.domain_events)
```

### Span Attributes

Add meaningful context:

```python
with tracer.start_as_current_span("process_task") as span:
    # ✅ Good attributes
    span.set_attribute("task.id", task.id)
    span.set_attribute("task.priority", task.priority.value)
    span.set_attribute("task.status", task.status.value)
    span.set_attribute("user.id", user_id)
    span.set_attribute("operation.retry_count", retry_count)

    # ❌ Bad attributes
    span.set_attribute("task", str(task))  # Too large
    span.set_attribute("user.password", password)  # Sensitive
    span.set_attribute("data", json.dumps(data))  # Unstructured
```

## Error Handling

### Recording Exceptions

Always record exceptions in spans:

```python
# ✅ Good: Record exception with context
try:
    await repository.save(task)
except ValidationError as e:
    span.record_exception(e)
    span.set_status(Status(StatusCode.ERROR, "Validation failed"))
    span.set_attribute("error.type", "validation")
    span.set_attribute("error.field", e.field)
    raise

except Exception as e:
    span.record_exception(e)
    span.set_status(Status(StatusCode.ERROR, str(e)))
    span.set_attribute("error.type", type(e).__name__)
    raise
```

### Error Metrics

Track errors with metrics:

```python
# ✅ Good: Separate error counter
tasks_failed = meter.create_counter(
    name="lablet_cloud_manager.tasks.failed",
    description="Total failed task operations",
    unit="1"
)

try:
    await process_task(task)
    tasks_completed.add(1, {"priority": task.priority})
except Exception as e:
    tasks_failed.add(1, {
        "priority": task.priority,
        "error_type": type(e).__name__
    })
    raise
```

## Sampling Strategies

### Development

```bash
# 100% sampling
OTEL_TRACES_SAMPLER=always_on
```

### Production

**Option 1: Probabilistic (Simple)**

```bash
# Sample 10% of all traces
OTEL_TRACES_SAMPLER=traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1
```

**Option 2: Parent-based (Recommended)**

```bash
# Sample 10%, but respect parent sampling decision
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1
```

**Option 3: Tail Sampling (Advanced)**

Use OTEL Collector tail sampling:

```yaml
processors:
  tail_sampling:
    policies:
      # Always sample errors
      - name: error-policy
        type: status_code
        status_code:
          status_codes: [ERROR]

      # Always sample slow requests
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

## Cost Management

### Development Environment

**Full instrumentation**:

```bash
OTEL_TRACES_SAMPLER=always_on
OTEL_METRICS_EXPORTER=otlp
OTEL_LOG_LEVEL=debug
```

**Estimated cost**: Minimal (local infrastructure)

### Staging Environment

**Moderate sampling**:

```bash
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=0.5  # 50% sampling
```

**Estimated cost**: Low to moderate

### Production Environment

**Intelligent sampling**:

```bash
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1  # 10% sampling
```

**Plus tail sampling**:

- 100% errors
- 100% slow requests (> 500ms)
- 10% normal requests

**Estimated cost**: Moderate (depends on traffic)

### Cost Optimization Tips

1. **Reduce trace volume**:
   - Lower sampling rate
   - Use tail sampling
   - Set shorter retention periods

2. **Reduce span attributes**:
   - Remove verbose attributes
   - Truncate long strings
   - Avoid nested objects

3. **Reduce metric cardinality**:
   - Limit label values
   - Remove unnecessary labels
   - Use aggregations

4. **Configure retention**:
   - Traces: 7-30 days
   - Metrics: 30-90 days
   - Adjust based on needs

## Security

### Don't Log Sensitive Data

**❌ Never include**:

```python
# Bad: PII and secrets
span.set_attribute("user.email", email)
span.set_attribute("user.ssn", ssn)
span.set_attribute("user.password", password)
span.set_attribute("api_key", api_key)
span.set_attribute("credit_card", cc_number)
```

**✅ Use opaque identifiers**:

```python
# Good: Non-sensitive IDs
span.set_attribute("user.id", user_id)  # UUID
span.set_attribute("session.id", session_id)
span.set_attribute("request.id", request_id)
```

### Scrub Sensitive Attributes

Use OTEL Collector attribute processor:

```yaml
processors:
  attributes:
    actions:
      # Remove sensitive attributes
      - key: user.email
        action: delete

      - key: user.ssn
        action: delete

      # Hash PII
      - key: user.ip
        action: hash
```

### Secure Communication

**Enable TLS**:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=https://otel-collector:4317
OTEL_EXPORTER_OTLP_CERTIFICATE=/path/to/cert.pem
```

**Use authentication**:

```bash
OTEL_EXPORTER_OTLP_HEADERS=api-key=your-secret-key
```

## Performance

### Minimize Overhead

**1. Async operations**:

OpenTelemetry SDK is async by default - no blocking.

**2. Batch exports**:

```yaml
processors:
  batch:
    timeout: 10s
    send_batch_size: 512
```

**3. Don't over-instrument**:

```python
# ❌ Bad: Too granular
for item in items:  # 10,000 iterations
    with tracer.start_as_current_span("process_item"):
        process(item)

# ✅ Good: Batch operation
with tracer.start_as_current_span("process_items") as span:
    span.set_attribute("items.count", len(items))
    for item in items:
        process(item)
```

### Monitor Overhead

Track observability overhead:

```python
# Measure instrumentation impact
import time

start = time.perf_counter()
# Operation with instrumentation
duration = time.perf_counter() - start

# Overhead should be < 5% of operation time
```

**Typical overhead**:

- Metrics: < 1ms per recording
- Traces: < 5ms per span
- Total: < 5% of operation time

## Common Patterns

### Command Handler Pattern

```python
async def handle_create_task(command: CreateTaskCommand) -> OperationResult:
    with tracer.start_as_current_span("handle_create_task_command") as span:
        span.set_attribute("command.type", "CreateTaskCommand")
        span.set_attribute("task.priority", command.priority)

        try:
            # Validation
            with tracer.start_as_current_span("validate_command"):
                validate(command)

            # Business logic
            task = await create_task(command)

            # Record success metric
            tasks_created.add(1, {"priority": command.priority})

            span.set_status(Status(StatusCode.OK))
            return OperationResult.success(task)

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR))
            tasks_failed.add(1, {"priority": command.priority})
            raise
```

### Repository Pattern

```python
class TaskRepository:
    def __init__(self):
        self.tracer = trace.get_tracer(__name__)

    async def save(self, task: Task) -> Task:
        with self.tracer.start_as_current_span("task_repository.save") as span:
            span.set_attribute("task.id", task.id)
            span.set_attribute("repository.operation", "save")

            # MongoDB save (auto-instrumented)
            result = await self.collection.insert_one(task.to_dict())

            return task
```

## Related Documentation

- [Observability Overview](./overview.md) - Concepts and introduction
- [Metrics Guide](./metrics.md) - Metrics implementation
- [Tracing Guide](./tracing.md) - Tracing implementation
- [Configuration](./configuration.md) - Configuration options

## Additional Resources

- [OpenTelemetry Best Practices](https://opentelemetry.io/docs/concepts/signals/)
- [Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/)
- [Cost Management Guide](https://opentelemetry.io/docs/concepts/data-collection/)
