#!/bin/bash
# Keycloak Master Realm SSL Configuration Script
# This script disables SSL requirement for the master realm in Keycloak
# Run this after Keycloak starts to allow HTTP access to admin console

set -e

echo "🔐 Configuring Keycloak master realm SSL settings..."

# Wait for Keycloak to be ready
echo "⏳ Waiting for Keycloak to be ready..."
sleep 20

# Configure kcadm credentials
echo "📝 Configuring kcadm credentials..."
docker exec lablet-cloud-manager-keycloak-1 /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 \
  --realm master \
  --user admin \
  --password admin

# Update master realm to disable SSL requirement
echo "🔓 Disabling SSL requirement for master realm..."
docker exec lablet-cloud-manager-keycloak-1 /opt/keycloak/bin/kcadm.sh update realms/master \
  -s sslRequired=NONE

echo "✅ Master realm SSL configuration complete!"
echo "🌐 You can now access the admin console at: http://localhost:8090"
