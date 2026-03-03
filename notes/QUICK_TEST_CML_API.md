# Quick Test Guide: CML API Integration

## Prerequisites

1. **Start MongoDB** (if not running):

   ```bash
   docker-compose up -d mongodb
   ```

2. **Check worker status**:

   ```bash
   docker-compose exec mongodb mongosh lablet_cloud_manager --quiet \
     --eval "db.cml_workers.find({}, {name:1, status:1, service_status:1, https_endpoint:1, public_ip:1}).pretty()"
   ```

   **Looking for:**
   - `status: "running"`
   - `service_status: "available"`
   - `https_endpoint: "https://..."`  (not null)

## Run Tests

### Option 1: Test All Workers

```bash
.venv/bin/python scripts/test_cml_api.py --test-all --password <cml-password>
```

### Option 2: Test Specific Worker by ID

```bash
.venv/bin/python scripts/test_cml_api.py \
  --worker-id 9b42b7e7-af50-4b55-ac1a-e0d9f00eefdf \
  --password <cml-password>
```

### Option 3: Test Specific Endpoint Directly

```bash
.venv/bin/python scripts/test_cml_api.py \
  --endpoint https://52.1.2.3 \
  --username admin \
  --password <cml-password>
```

## Expected Output

### Success

```
2025-11-17 00:00:00,000 - __main__ - INFO - Testing CML API at: https://52.1.2.3
2025-11-17 00:00:00,100 - __main__ - INFO - Step 1: Testing authentication...
2025-11-17 00:00:00,200 - __main__ - INFO - ✅ Authentication successful! Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

2025-11-17 00:00:00,300 - __main__ - INFO - Step 2: Testing system_stats endpoint...
2025-11-17 00:00:00,400 - __main__ - INFO - ✅ Successfully retrieved system stats!

=== System Statistics ===
CPU: 8 cores @ 15.23% utilization
Memory: 4.52 GB used / 15.23 GB total
Disk: 12.34 GB used / 50.00 GB total

=== CML Workload ===
Allocated CPUs: 4
Allocated Memory: 2048.00 MB
Total Nodes: 10
Running Nodes: 8

=== Compute Nodes ===
  cml-controller (controller=True)

2025-11-17 00:00:00,500 - __main__ - INFO - ✅ All tests passed for https://52.1.2.3
```

### Failure (Worker Not Ready)

```
2025-11-17 00:00:00,000 - __main__ - ERROR - ❌ Worker has no HTTPS endpoint configured
```

or

```
2025-11-17 00:00:00,000 - __main__ - WARNING - ⚠️  Worker service is not AVAILABLE (status: unavailable)
```

or

```
2025-11-17 00:00:00,000 - __main__ - ERROR - ❌ Cannot connect to CML instance: Connection refused
```

## Troubleshooting

### Issue: `ModuleNotFoundError: No module named 'motor'`

**Solution:**

```bash
cd /Users/bvandewe/Documents/Work/Systems/Mozart/src/microservices/lablet-cloud-manager
poetry install
```

### Issue: Connection Timeout

**Check:**

1. Worker instance is running in AWS
2. Security group allows HTTPS (port 443) from your IP
3. CML service is actually running on the instance

```bash
# SSH to worker and check CML status
ssh -i <key> ubuntu@<worker-ip>
sudo systemctl status virl2
```

### Issue: Authentication Failed (401/403)

**Check:**

1. CML password in settings: `src/application/settings.py`
2. Default is "admin" / "admin" - change in production!
3. Try logging into CML web UI to verify credentials

### Issue: SSL Certificate Error

**Expected behavior:**

- Script uses `verify_ssl=False` for self-signed certs
- This is normal for CML instances with self-signed certificates

## Verify Integration

After successful test, check that metrics are populated:

```bash
# Check worker state in database
docker-compose exec mongodb mongosh lablet_cloud_manager --quiet \
  --eval "db.cml_workers.findOne({https_endpoint: {\$ne: null}}, {cml_system_info:1, cml_ready:1, cml_labs_count:1, cml_last_synced_at:1})"
```

**Should see:**

- `cml_system_info: { ... }`
- `cml_ready: true`
- `cml_labs_count: <number>`
- `cml_last_synced_at: ISODate("2025-11-17...")`

## Next Steps

Once testing succeeds:

1. ✅ Update TODO.md - mark "Test CML API Integration" as complete
2. Monitor RefreshWorkerMetricsCommand logs for CML data collection
3. Check OTEL metrics for `cml_labs_count` gauge
4. Test token auto-refresh (run overnight, check logs next day)
