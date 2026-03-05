# Performance Testing with Locust

This directory contains load testing scenarios for the Lablet Cloud Manager API using [Locust](https://locust.io/).

## Prerequisites

Install Locust:

```bash
pip install locust
```

## Running Load Tests

### Basic Test Run

Start Locust with the web UI:

```bash
cd tests/performance
locust -f locustfile.py --host=http://localhost:8020
```

Then open <http://localhost:8089> to configure and start the test.

### Headless Mode (CI/CD)

Run without the web UI:

```bash
locust -f locustfile.py --host=http://localhost:8020 \
    --headless \
    --users 50 \
    --spawn-rate 10 \
    --run-time 5m \
    --html report.html
```

### Specific Scenarios

Run specific test scenarios:

```bash
# Instance creation scenario
locust -f scenarios/instance_scenarios.py --host=http://localhost:8020

# Scheduling stress test
locust -f scenarios/scheduling_scenarios.py --host=http://localhost:8020

# Full API coverage
locust -f locustfile.py --host=http://localhost:8020
```

## Test Scenarios

### `locustfile.py` - Main Test Suite

Combined test suite covering all major API endpoints:

- Instance CRUD operations
- Worker management
- Definition queries
- Scheduling operations

### `scenarios/instance_scenarios.py` - Instance Operations

Focused testing of instance lifecycle:

- Create instance (high weight)
- List instances with pagination
- Get instance details
- Terminate instances

### `scenarios/scheduling_scenarios.py` - Scheduling Load

Stress testing for scheduler:

- Concurrent instance creation
- Scheduling decision timing
- Worker assignment latency

## Performance Targets (NFR)

| Metric | Target |
|--------|--------|
| API response time (p95) | < 500ms |
| Scheduling decision time | < 5s |
| Instantiation time | < 3 min |
| Concurrent instances | 1000+ |

## Analyzing Results

Locust generates:

- Real-time statistics in the web UI
- HTML reports with `--html` flag
- CSV exports with `--csv` flag

Key metrics to watch:

- Response time percentiles (p50, p95, p99)
- Requests per second (RPS)
- Failure rate
- Number of concurrent users

## CI Integration

See `.github/workflows/performance.yml` for CI pipeline integration.

```yaml
# Example GitHub Actions step
- name: Run Load Tests
  run: |
    locust -f tests/performance/locustfile.py \
      --host=${{ env.API_URL }} \
      --headless \
      --users 100 \
      --spawn-rate 20 \
      --run-time 10m \
      --csv=results \
      --html=report.html
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LCM_API_HOST` | API host URL | `http://localhost:8020` |
| `LCM_AUTH_TOKEN` | Bearer token for auth | - |
| `LCM_DEFINITION_ID` | Test definition ID | `test-definition` |

## Troubleshooting

### Authentication Errors

If tests fail with 401 errors, ensure:

1. The API is running
2. Auth token is valid
3. Test user has required permissions

### Connection Errors

If tests fail to connect:

1. Check the host URL
2. Verify network connectivity
3. Check CORS settings if testing from browser
