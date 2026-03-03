# Nginx Reverse Proxy

The Nginx service acts as the single entry point for the Lablet Cloud Manager production stack. It handles routing, SSL termination (optional), caching, and security headers.

## Configuration

The main configuration file is located at `deployment/nginx/conf.d/lablet-cloud-manager.conf`.

### Routing

- **`/`**: Proxies to the main application (API + UI).
- **`/api/v1/`**: Proxies to the Event Player API.
- **`/events/`**: Proxies to the Event Player UI.
- **`/grafana/`**: Proxies to the Grafana dashboard.
- **`/auth/`**: Proxies to the Keycloak identity provider.

### Security

- **Rate Limiting**:
  - `api_limit`: 10 requests/second (burst 20) for general API endpoints.
  - `auth_limit`: 5 requests/second (burst 5) for authentication endpoints.
- **Headers**:
  - `Strict-Transport-Security`: Enforces HTTPS.
  - `Content-Security-Policy`: Restricts sources for scripts, styles, and images.

### Caching

- Static assets (`/static/`) are cached for 1 hour.
- SSE endpoints (`/events/`, `/api/events/stream`) have buffering disabled to ensure real-time delivery.

## Maintenance

To apply configuration changes without downtime:

```bash
make prod-restart-service SERVICE=nginx
```
