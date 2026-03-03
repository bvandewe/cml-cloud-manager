# Known Issues and Troubleshooting

This document catalogs known issues, bugs, and their workarounds.

## Framework Issues

### Neuroglia MongoDB Import Bug

**Status**: Reported to framework maintainers
**Severity**: Medium
**Affects**: Projects using Motor (async MongoDB) without PyMongo

#### Description

The Neuroglia package `neuroglia-data-motor` has an import bug in its `__init__.py` that causes unnecessary dependency on `pymongo` even when using only async Motor driver.

#### Root Cause

File: `neuroglia/data/motor/__init__.py`

```python
from .enhanced_mongo_repository import EnhancedMongoRepository  # ❌ Problem
```

`EnhancedMongoRepository` requires `pymongo` (sync driver) but most users only need `MotorRepository` (async).

#### Impact

- Forces installation of unused `pymongo` dependency
- Larger dependency tree
- Potential version conflicts
- Import fails if pymongo not installed

#### Workaround

Add `pymongo` to dependencies even though not directly used:

```toml
# pyproject.toml
[tool.poetry.dependencies]
neuroglia-data-motor = "^0.3.1"
pymongo = "^4.10.1"  # Workaround for Neuroglia bug
```

#### Proposed Solutions

Three possible fixes for framework:

1. **Lazy Import** (Recommended)

   ```python
   # __init__.py
   __all__ = ['MotorRepository', 'EnhancedMongoRepository']

   def __getattr__(name):
       if name == 'MotorRepository':
           from .motor_repository import MotorRepository
           return MotorRepository
       elif name == 'EnhancedMongoRepository':
           from .enhanced_mongo_repository import EnhancedMongoRepository
           return EnhancedMongoRepository
       raise AttributeError(f"module {__name__} has no attribute {name}")
   ```

2. **Separate Package**
   - Create `neuroglia-data-mongo` for sync operations
   - Keep `neuroglia-data-motor` async-only

3. **Optional Dependency**

   ```python
   try:
       from .enhanced_mongo_repository import EnhancedMongoRepository
   except ImportError:
       EnhancedMongoRepository = None
   ```

#### Related Files

- Bug report: `docs/troubleshooting/neuroglia-mongo-import.md`
- Workaround in: `pyproject.toml`

---

## Environment Issues

### Python Version Mismatch

**Symptom**: `ModuleNotFoundError` or import errors after environment recreation

**Cause**: VS Code/Pylance caching old environment

**Solution**:

1. Reload VS Code window:
   - Cmd+Shift+P → "Developer: Reload Window"

2. Or restart VS Code completely

3. Verify Python version:

   ```bash
   python --version  # Should show 3.11+
   ```

### Poetry Install Hangs

**Symptom**: `poetry install` appears stuck

**Causes**:

- Large dependency resolution
- Network issues
- Lock file conflicts

**Solutions**:

```bash
# Clear cache
poetry cache clear pypi --all

# Try with verbose output
poetry install -vvv

# Or skip existing packages
poetry install --no-root
```

### PYTHONPATH Issues

**Symptom**: "ModuleNotFoundError: No module named 'src'"

**Solution**: Ensure `src/` is in PYTHONPATH

```bash
# Option 1: Export in shell
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Option 2: Add to .env
PYTHONPATH=/path/to/project

# Option 3: Run with python -m
python -m uvicorn src.main:app
```

---

## Docker Issues

### Port Already Allocated

**Symptom**: "port is already allocated" error

**Check what's using port**:

```bash
lsof -i :8020  # Check specific port
```

**Solutions**:

1. Stop conflicting service
2. Change port in `.env`:

   ```bash
   APP_PORT=8021
   ```

3. Kill process using port:

   ```bash
   kill -9 $(lsof -ti:8020)
   ```

### Volume Mount Not Working

**Symptom**: Code changes don't trigger reload

**Check mounts**:

```bash
docker compose config | grep volumes -A 5
```

**Solutions**:

1. Restart container:

   ```bash
   docker compose restart app
   ```

2. Rebuild without cache:

   ```bash
   docker compose build --no-cache app
   ```

3. Verify paths in `docker-compose.yml`:

   ```yaml
   volumes:
     - ./src:/app/src  # Relative to docker-compose.yml
   ```

### Redis Connection Refused

**Symptom**: "Connection refused to redis:6379"

**Check Redis is running**:

```bash
docker compose ps redis
docker compose logs redis
```

**Solutions**:

1. Start Redis:

   ```bash
   docker compose up -d redis
   ```

2. Check network:

   ```bash
   docker compose exec app ping redis
   ```

3. Verify configuration in `.env`:

   ```bash
   REDIS_HOST=redis  # Service name in docker-compose
   REDIS_PORT=6379
   ```

---

## Authentication Issues

### Session Not Found (401 Errors)

**Symptom**: Authenticated user suddenly gets 401

**Causes**:

- Session expired (TTL reached)
- Redis restarted (sessions lost)
- Cookie not sent

**Debug**:

```bash
# Check Redis has sessions
docker compose exec redis redis-cli KEYS "session:*"

# Check cookie in browser DevTools
# Application → Cookies → session_id
```

**Solutions**:

1. Increase TTL in settings:

   ```python
   SESSION_TTL = 7200  # 2 hours
   ```

2. Enable Redis persistence:

   ```yaml
   redis:
     command: redis-server --appendonly yes
     volumes:
       - redis_data:/data
   ```

3. Check SameSite settings if cross-origin:

   ```python
   response.set_cookie(
       "session_id",
       value=session_id,
       samesite="none",  # For cross-origin
       secure=True       # Required with samesite=none
   )
   ```

### Keycloak Redirect Loop

**Symptom**: Infinite redirects between app and Keycloak

**Causes**:

- Wrong redirect URI configuration
- CORS issues
- Cookie not being set

**Check Keycloak client config**:

- Admin Console → Clients → lablet-cloud-manager-client
- Valid Redirect URIs: `http://localhost:8020/*`
- Web Origins: `http://localhost:8020`

**Check application config**:

```python
KEYCLOAK_REDIRECT_URI = "http://localhost:8020/api/auth/callback"
```

Must match Keycloak configuration exactly.

---

## Database Issues

### MongoDB Connection Timeout

**Symptom**: "ServerSelectionTimeoutError"

**Check MongoDB**:

```bash
docker compose ps mongodb
docker compose logs mongodb
```

**Test connection**:

```bash
docker compose exec mongodb mongosh -u root -p neuroglia123
```

**Solutions**:

1. Verify connection string format:

   ```
   mongodb://root:neuroglia123@mongodb:27017/lablet_cloud_manager?authSource=admin
   ```

2. Check network connectivity:

   ```bash
   docker compose exec app ping mongodb
   ```

3. Increase timeout in Motor config:

   ```python
   client = AsyncIOMotorClient(
       connection_string,
       serverSelectionTimeoutMS=5000
   )
   ```

### Collection Not Found

**Symptom**: Operations fail with "collection doesn't exist"

**Cause**: MongoDB creates collections on first write

**Solution**: Collections auto-created on first document insert. For explicit creation:

```python
# In setup/initialization code
await database.create_collection("tasks")
```

---

## Frontend Issues

### Bootstrap Not Defined

**Symptom**: `ReferenceError: bootstrap is not defined`

**Cause**: Missing import in module

**Solution**: Import Bootstrap in file using it:

```javascript
import * as bootstrap from 'bootstrap';

// Then use
const modal = new bootstrap.Modal(element);
```

### Module Not Found

**Symptom**: "Failed to resolve module specifier"

**Causes**:

- Wrong import path
- Missing file extension
- Case sensitivity

**Solutions**:

```javascript
// ✅ Correct - relative path with extension
import { getTasks } from './api/tasks.js';

// ❌ Wrong - absolute path
import { getTasks } from '/api/tasks.js';

// ❌ Wrong - no extension
import { getTasks } from './api/tasks';
```

### Styles Not Loading

**Symptom**: Unstyled content

**Check**:

1. Build completed successfully:

   ```bash
   docker compose logs ui-builder
   ```

2. CSS file exists:

   ```bash
   ls static/ui.*.css
   ```

3. HTML references CSS:

   ```bash
   cat static/index.html | grep "\.css"
   ```

**Solution**: Rebuild UI:

```bash
make build-ui
# or
docker compose restart ui-builder
```

---

## General Debugging

### Enable Debug Logging

```bash
# .env file
LOG_LEVEL=DEBUG

# Or temporarily
export LOG_LEVEL=DEBUG
make run
```

### View All Container Logs

```bash
docker compose logs -f --tail=100
```

### Check Service Health

```bash
# Application health
curl http://localhost:8020/health

# MongoDB
docker compose exec mongodb mongosh --eval "db.runCommand({ping: 1})"

# Redis
docker compose exec redis redis-cli ping

# Keycloak
curl http://localhost:8090/health
```

### Clean State Reset

```bash
# Stop everything
docker compose down

# Remove volumes (⚠️ deletes data)
docker compose down -v

# Rebuild
docker compose build --no-cache

# Start fresh
docker compose up -d
```

---

## Getting Help

### Check Documentation

- [Architecture Overview](../architecture/overview.md) - Design patterns
- [Docker Environment](../deployment/docker-environment.md) - Environment setup
- [Frontend Build Process](../frontend/build-process.md) - UI build process

### Logs and Diagnostics

```bash
# Application logs
docker compose logs app

# All services
make docker-logs

# System info
make status
```

### Create Issue

If you find a new bug:

1. Check if already documented here
2. Gather logs and error messages
3. Create minimal reproduction steps
4. Document in this file or create GitHub issue

---

## Related Documentation

- [Neuroglia MongoDB Bug](./neuroglia-mongo-import.md) - Detailed bug report
- [Docker Environment](../infrastructure/docker-environment.md) - Service setup
- [Makefile Reference](../development/makefile-reference.md) - Command reference
- [Getting Started](../getting-started/running-the-app.md) - Running the application
