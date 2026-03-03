# Nginx Reverse Proxy Configuration Guide

## Overview

The production stack uses **Nginx as a reverse proxy** to provide:

- **Single entry point** on port 80 (HTTP) / 443 (HTTPS when configured)
- **Security headers** (XSS protection, CSP, frame options)
- **Rate limiting** (10 req/s for API, 5 req/s for auth endpoints)
- **Compression** (gzip for text content)
- **SSL/TLS termination** (when certificates are configured)
- **Load balancing** (ready for horizontal scaling)
- **Static file caching**
- **WebSocket support** (for SSE and event streaming)

## Architecture

```
Internet/Clients
     ↓
  [Nginx:80] ← Single entry point
     ↓
     ├─→ [API Service:8000] ── Application endpoints
     ├─→ [Keycloak:8080] ──── Authentication at /auth
     ├─→ [Grafana:3000] ───── grafana.localhost
     ├─→ [Prometheus:9090] ── prometheus.localhost
     └─→ [Event Player:8080] - event-player.localhost
```

## Configuration Files

### Main Configuration

- **`deployment/nginx/nginx.conf`**: Main nginx config
  - Worker processes, logging, gzip compression
  - Security headers (global)
  - Rate limiting zones
  - Upstream server definitions

### Site Configurations (conf.d/)

- **`lablet-cloud-manager.conf`**: Main application (localhost)
  - Routes `/` to API service
  - Routes `/api/` with rate limiting
  - Routes `/auth/` to Keycloak
  - Routes `/static/` with caching

- **`grafana.conf`**: Grafana dashboard (grafana.localhost)
- **`prometheus.conf`**: Prometheus UI (prometheus.localhost)
- **`keycloak.conf`**: Keycloak admin console (keycloak.localhost)
- **`event-player.conf`**: Event visualization (event-player.localhost)

## Access Methods

### 1. Main Domain (localhost)

All requests to `http://localhost` are proxied to the API service:

```bash
# Application UI
curl http://localhost

# API endpoints
curl http://localhost/api/workers

# Health check
curl http://localhost/health

# Keycloak (via /auth path)
curl http://localhost/auth/realms/lablet-cloud-manager
```

### 2. Subdomain Routing (*.localhost)

Configure subdomains in `/etc/hosts` or DNS:

```bash
# /etc/hosts (local development)
127.0.0.1 grafana.localhost
127.0.0.1 prometheus.localhost
127.0.0.1 keycloak.localhost
127.0.0.1 event-player.localhost
```

Then access services:

```bash
# Grafana
http://grafana.localhost

# Prometheus
http://prometheus.localhost

# Keycloak
http://keycloak.localhost

# Event Player
http://event-player.localhost
```

### 3. Direct Service Access (bypass nginx)

Some services remain directly accessible:

```bash
# Keycloak admin console (kept for direct access)
http://localhost:8090

# Prometheus (optional direct access)
http://localhost:9090

# MongoDB Express
http://localhost:8081
```

## Rate Limiting

Nginx implements rate limiting to protect against abuse:

### API Endpoints

- **Zone**: `api_limit`
- **Rate**: 10 requests/second
- **Burst**: 20 requests (allows brief spikes)
- **Applies to**: All `/api/` paths

### Authentication Endpoints

- **Zone**: `auth_limit`
- **Rate**: 5 requests/second
- **Burst**: 5 requests
- **Applies to**: `/api/auth/` paths

### Exemptions

- Health checks (`/health`) - no rate limiting
- Metrics (`/metrics`) - no rate limiting
- Static files (`/static/`) - standard API rate limiting

## Security Headers

Nginx adds security headers to all responses:

```
X-Frame-Options: SAMEORIGIN
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Strict-Transport-Security: max-age=31536000 (HTTPS only)
Content-Security-Policy: [configured per application]
```

## SSL/TLS Configuration (Optional)

To enable HTTPS:

### 1. Generate or obtain SSL certificates

**Self-signed (development):**

```bash
mkdir -p deployment/nginx/ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout deployment/nginx/ssl/nginx-selfsigned.key \
  -out deployment/nginx/ssl/nginx-selfsigned.crt
```

**Let's Encrypt (production):**
Use certbot or integrate with a certificate manager.

### 2. Update docker-compose.prod.yml

Uncomment SSL port and volume:

```yaml
nginx:
  ports:
    - "80:80"
    - "443:443"  # Uncomment this
  volumes:
    - ../nginx/ssl:/etc/nginx/ssl:ro  # Uncomment this
```

### 3. Create SSL configuration

Create `deployment/nginx/conf.d/ssl.conf`:

```nginx
server {
    listen 443 ssl http2;
    server_name localhost;

    ssl_certificate /etc/nginx/ssl/nginx-selfsigned.crt;
    ssl_certificate_key /etc/nginx/ssl/nginx-selfsigned.key;

    # Modern SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Rest of configuration same as http...
    location / {
        proxy_pass http://cml_api;
        # ... same proxy settings
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name localhost;
    return 301 https://$host$request_uri;
}
```

## Load Balancing

Nginx is configured for load balancing. To scale the API service:

```bash
# Scale API to 3 instances
docker-compose -f deployment/docker-compose/docker-compose.prod.yml \
  --env-file deployment/docker-compose/.env.prod \
  up -d --scale api=3
```

Nginx will automatically distribute requests across instances using round-robin.

### Advanced Load Balancing

Edit `deployment/nginx/nginx.conf` to customize:

```nginx
upstream cml_api {
    # Least connections algorithm
    least_conn;

    server api:8000 max_fails=3 fail_timeout=30s weight=1;
    # Add more servers manually if needed
    # server api2:8000 max_fails=3 fail_timeout=30s weight=1;

    keepalive 32;
}
```

## Custom Configuration

### Adding New Routes

1. Create a new config file in `deployment/nginx/conf.d/`:

```nginx
# deployment/nginx/conf.d/custom-service.conf
server {
    listen 80;
    server_name myservice.localhost;

    location / {
        proxy_pass http://myservice:8080;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

2. Restart nginx:

```bash
docker-compose -f deployment/docker-compose/docker-compose.prod.yml restart nginx
```

### Adjusting Rate Limits

Edit `deployment/nginx/nginx.conf`:

```nginx
# Increase API rate limit to 20 req/s
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=20r/s;

# Increase auth rate limit to 10 req/s
limit_req_zone $binary_remote_addr zone=auth_limit:10m rate=10r/s;
```

### IP Whitelisting

Restrict access to certain endpoints by IP:

```nginx
location /api/admin/ {
    # Allow specific IPs
    allow 192.168.1.0/24;
    allow 10.0.0.0/8;
    deny all;

    proxy_pass http://cml_api;
}
```

## Monitoring & Logging

### Access Logs

View nginx access logs:

```bash
# Via docker logs
docker-compose -f deployment/docker-compose/docker-compose.prod.yml logs -f nginx

# Via volume
docker exec lablet-cloud-manager-nginx tail -f /var/log/nginx/access.log
```

### Error Logs

```bash
docker exec lablet-cloud-manager-nginx tail -f /var/log/nginx/error.log
```

### Log Format

Logs include timing information:

```
remote_addr - user [time] "request" status bytes "referer" "user_agent"
rt=request_time uct=upstream_connect_time uht=upstream_header_time urt=upstream_response_time
```

### Prometheus Metrics

Nginx can export metrics for Prometheus:

1. Add nginx-prometheus-exporter to docker-compose
2. Configure nginx stub_status module
3. Scrape metrics in Prometheus

## Troubleshooting

### Check Nginx Configuration

```bash
# Test configuration syntax
docker exec lablet-cloud-manager-nginx nginx -t

# Reload configuration without downtime
docker exec lablet-cloud-manager-nginx nginx -s reload
```

### Debug Proxy Issues

Enable debug logging temporarily:

```nginx
# In nginx.conf
error_log /var/log/nginx/error.log debug;
```

### Common Issues

**502 Bad Gateway**

- Backend service is down or not responding
- Check backend health: `curl http://api:8000/health`

**504 Gateway Timeout**

- Request taking too long
- Increase timeouts in nginx config:

  ```nginx
  proxy_connect_timeout 600s;
  proxy_send_timeout 600s;
  proxy_read_timeout 600s;
  ```

**Rate Limit Errors (429)**

- Client exceeding rate limits
- Increase burst parameter or rate
- Check logs: `grep "limiting requests" /var/log/nginx/access.log`

**Subdomain Not Working**

- Check /etc/hosts configuration
- Verify DNS resolution
- Check nginx server_name directive

## Best Practices

1. **Always use nginx** for production deployments
2. **Enable HTTPS/TLS** with valid certificates
3. **Set appropriate rate limits** based on expected traffic
4. **Monitor nginx logs** for errors and performance
5. **Keep nginx updated** (use latest stable image)
6. **Use subdomain routing** for clean URL structure
7. **Configure CORS properly** for API endpoints
8. **Implement IP whitelisting** for admin endpoints
9. **Set up log rotation** for production
10. **Test configuration changes** before applying

## Performance Tuning

### Worker Processes

```nginx
# nginx.conf
worker_processes auto;  # Automatically detect CPU cores
```

### Connection Limits

```nginx
events {
    worker_connections 2048;  # Increase for high traffic
}
```

### Buffer Sizes

```nginx
http {
    client_body_buffer_size 128k;
    client_max_body_size 100M;
    client_header_buffer_size 1k;
    large_client_header_buffers 4 16k;
}
```

### Caching

Enable proxy caching for better performance:

```nginx
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=api_cache:10m max_size=1g inactive=60m;

location /api/static/ {
    proxy_cache api_cache;
    proxy_cache_valid 200 1h;
    proxy_cache_key "$scheme$request_method$host$request_uri";
}
```

## Additional Resources

- [Nginx Official Documentation](https://nginx.org/en/docs/)
- [Nginx Reverse Proxy Guide](https://docs.nginx.com/nginx/admin-guide/web-server/reverse-proxy/)
- [SSL Configuration Generator](https://ssl-config.mozilla.org/)
- [Nginx Rate Limiting](https://www.nginx.com/blog/rate-limiting-nginx/)
