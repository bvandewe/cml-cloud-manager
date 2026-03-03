# Observability Overview

This guide provides an overview of observability in the Cml Cloud Manager, covering the three pillars of observability and how they work together to help you understand your system.

## Table of Contents

- [What is Observability?](#what-is-observability)
- [The Three Pillars](#the-three-pillars)
- [Quick Links](#quick-links)
- [Getting Started](#getting-started)
- [Common Use Cases](#common-use-cases)

## What is Observability?

**Observability** is the ability to understand the internal state of a system by examining its external outputs. Unlike monitoring (which tells you _what_ is broken), observability helps you understand _why_ it's broken.

### Observability vs Monitoring

| Aspect | Monitoring | Observability |
|--------|-----------|---------------|
| **Focus** | Known failures | Unknown failures |
| **Approach** | Predefined dashboards | Exploratory analysis |
| **Questions** | "Is the system up?" | "Why is it behaving this way?" |
| **Data** | Aggregated metrics | High-cardinality data |
| **Response** | Alert on thresholds | Investigate root cause |

### Why Observability Matters

- **Debug Production Issues**: Understand complex distributed system behavior
- **Performance Optimization**: Identify bottlenecks and optimize slow operations
- **User Experience**: Track real user impact of bugs and performance issues
- **Business Insights**: Correlate technical metrics with business outcomes
- **Proactive Problem Detection**: Catch issues before they impact users

## The Three Pillars

The Cml Cloud Manager implements all three pillars of observability using OpenTelemetry:

### 1. Metrics

**What**: Numerical measurements aggregated over time.

**Examples**:

- Request count per endpoint
- Task creation rate
- Database query latency
- Memory usage

**Use Cases**:

- Dashboards and real-time monitoring
- Alerting on thresholds
- Capacity planning
- Performance trending

**Learn More**: [Metrics Guide](./metrics.md)

### 2. Traces

**What**: Request paths through your distributed system showing timing and relationships.

**Examples**:

- End-to-end request flow from API → Handler → Repository → Database
- Service dependencies and call graphs
- Operation timing and bottlenecks
- Error propagation paths

**Use Cases**:

- Debugging slow requests
- Understanding system architecture
- Finding performance bottlenecks
- Troubleshooting distributed transactions

**Learn More**: [Tracing Guide](./tracing.md)

### 3. Logs

**What**: Timestamped event records with contextual information.

**Examples**:

- Application errors and exceptions
- Business events (task created, user logged in)
- Debug information
- Security audit trails

**Use Cases**:

- Debugging specific issues
- Security auditing
- Compliance and audit trails
- Root cause analysis

**Status**: Structured logging implemented, OpenTelemetry log export disabled (using traditional logging).

## Quick Links

### Documentation

- **[Architecture](./architecture.md)** - Technical architecture and components
- **[Getting Started](./getting-started.md)** - Quick start guide and examples
- **[Configuration](./configuration.md)** - Environment variables and configuration options
- **[Best Practices](./best-practices.md)** - Naming conventions, cardinality control, and patterns
- **[Troubleshooting](./troubleshooting.md)** - Common issues and solutions

### Instrumentation Guides

- **[Metrics Guide](./metrics.md)** - How to add custom metrics
- **[Tracing Guide](./tracing.md)** - How to add custom spans

### Tools

- **Grafana**: http://localhost:3000 - View traces and metrics
- **Prometheus**: http://localhost:9090 - Query metrics directly
- **OTEL Collector**: http://localhost:4317 - Telemetry collection endpoint

## Getting Started

### 1. Start the Stack

```bash
# Start all services
make up
```

### 2. Generate Telemetry

```bash
# Make API requests
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"title": "Test Task", "priority": "high"}'
```

### 3. View Data

**Traces in Grafana**:

1. Open http://localhost:3000
2. Navigate to **Explore** → **Tempo**
3. Search for service: `lablet-cloud-manager`

**Metrics in Prometheus**:

1. Open http://localhost:9090
2. Execute query: `rate(lablet_cloud_manager_tasks_created_total[5m])`

**Full Guide**: See [Getting Started](./getting-started.md)

## Common Use Cases

### Debug a Slow Request

1. Find slow traces in Grafana/Tempo (> 500ms)
2. Identify the slowest span
3. Check database queries and N+1 patterns
4. Optimize with indexes, caching, or query improvements

**Full Workflow**: See [Getting Started - Workflow 1](./getting-started.md#workflow-1-debug-a-slow-request)

### Monitor Task Creation Rate

```promql
# View rate in Prometheus or Grafana
rate(lablet_cloud_manager_tasks_created_total[5m])

# Alert when rate drops
alert: TaskCreationRateLow
expr: rate(lablet_cloud_manager_tasks_created_total[5m]) < 1
```

**Full Workflow**: See [Getting Started - Workflow 2](./getting-started.md#workflow-2-monitor-task-creation)

### Root Cause Analysis

When a production error occurs:

1. Check logs for error message and trace ID
2. Find trace in Grafana/Tempo using trace ID
3. Analyze trace to see request path
4. Identify failure point (which span failed)
5. Check span attributes for context
6. Correlate with metrics in Prometheus

**Full Workflow**: See [Getting Started - Workflow 3](./getting-started.md#workflow-3-root-cause-analysis)

## Technology Stack

The Cml Cloud Manager uses:

- **[OpenTelemetry](https://opentelemetry.io/)** - Vendor-neutral instrumentation (CNCF project)
- **[OTEL Collector](https://opentelemetry.io/docs/collector/)** - Telemetry aggregation and routing
- **[Grafana Tempo](https://grafana.com/docs/tempo/)** - Distributed tracing backend
- **[Prometheus](https://prometheus.io/)** - Time-series metrics database
- **[Grafana](https://grafana.com/)** - Unified visualization and dashboards
- **[Neuroglia Observability](https://github.com/neuroglia-io/python-framework)** - Python framework integration

**Learn More**: See [Architecture](./architecture.md)

### Real-Time Channel & Observability

The SSE stream (see [Real-Time Updates](../architecture/realtime-updates.md)) complements traditional telemetry:

- Provides immediate surface-level visibility (connection health badge, live worker lifecycle toasts).
- Can be correlated with traces and metrics (e.g., a `worker.status.updated` event followed by related spans).
- Helps distinguish UI latency issues (e.g., missed events due to disconnect) from backend performance problems.

When troubleshooting, always check whether the SSE badge is `Live`; a disconnected badge can explain stale UI data even when metrics/traces look healthy.

## Next Steps

1. **[Read Architecture Guide](./architecture.md)** - Understand how components work together
2. **[Follow Getting Started](./getting-started.md)** - Set up and use observability features
3. **[Add Custom Metrics](./metrics.md)** - Instrument your code with metrics
4. **[Add Custom Traces](./tracing.md)** - Add spans to track operations
5. **[Review Best Practices](./best-practices.md)** - Follow observability patterns
6. **[Configure for Production](./configuration.md)** - Optimize settings for production

## Additional Resources

### OpenTelemetry

- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
- [Python SDK Reference](https://opentelemetry-python.readthedocs.io/)
- [Instrumentation Libraries](https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/instrumentation)

### Observability Concepts

- [The Three Pillars of Observability](https://www.oreilly.com/library/view/distributed-systems-observability/9781492033431/)
- [OpenTelemetry Best Practices](https://opentelemetry.io/docs/concepts/signals/)

### Backend Tools

- [Grafana Tempo Documentation](https://grafana.com/docs/tempo/)
- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)

### Framework

- [Neuroglia Observability Module](https://github.com/neuroglia-io/python-framework)
