# Keycloak Configuration Notes

## SSL/HTTPS Configuration

For development, SSL is disabled for both the `master` and `lablet-cloud-manager` realms.

### First-Time Setup

If you're deploying fresh (without the `keycloak_data` volume), you'll need to disable SSL for the master realm once:

```bash
# After first startup, run this command once:
docker compose exec keycloak /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://localhost:8021 \
    --realm master \
    --user admin \
    --password admin

docker compose exec keycloak /opt/keycloak/bin/kcadm.sh update realms/master \
    -s sslRequired=none
```

This setting is **persisted** in the `keycloak_data` Docker volume and will survive container restarts.

### Realm Configuration

- **Master Realm**: `sslRequired=none` (for admin console access)
- **Starter-App Realm**: `sslRequired=none` (configured in realm export)

### Production

For production deployments:

1. Enable SSL/HTTPS on your load balancer or reverse proxy
2. Set `sslRequired=external` for both realms
3. Update `KC_HOSTNAME_URL` and `KC_HOSTNAME_ADMIN_URL` to use HTTPS
4. Configure proper SSL certificates

## Persistent Storage

The `keycloak_data` volume stores:

- H2 database with all realm configurations
- User accounts and credentials
- Client configurations
- Custom realm settings (including SSL requirements)

**To reset Keycloak completely:**

```bash
docker compose down
docker volume rm lablet-cloud-manager_keycloak_data
docker compose up -d
# Then re-run the SSL configuration commands above
```
