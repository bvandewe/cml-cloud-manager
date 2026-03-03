#!/bin/bash
# Script to get details about an existing CML Worker

set -e

# Configuration
KEYCLOAK_URL="http://localhost:8031"
API_URL="http://localhost:8030"
REALM="lablet-cloud-manager"
CLIENT_ID="lablet-cloud-manager-public"
USERNAME="admin"
PASSWORD="test"  # pragma: allowlist secret
AWS_REGION="us-east-1"
WORKER_ID="${1:-507fb3ed-5603-4c26-8ffb-37d45221f5f5}"

echo "🔐 Authenticating with Keycloak..."

# Get access token from Keycloak
TOKEN_RESPONSE=$(curl -s -X POST \
  "${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=${USERNAME}" \
  -d "password=${PASSWORD}" \
  -d "grant_type=password" \
  -d "client_id=${CLIENT_ID}")

# Extract access token
ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

if [ -z "$ACCESS_TOKEN" ]; then
  echo "❌ Failed to get access token"
  echo "Response: $TOKEN_RESPONSE"
  exit 1
fi

echo "✅ Successfully authenticated"
echo ""
echo "📋 Getting worker details for ID: ${WORKER_ID}"

# Get worker details
WORKER_DETAILS=$(curl -s -X GET \
  "${API_URL}/api/workers/region/${AWS_REGION}/workers/${WORKER_ID}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json")

echo ""
echo "📊 Worker Details:"
echo "$WORKER_DETAILS" | jq '.'

echo ""
echo "✅ Summary:"
echo "   Worker Name: $(echo "$WORKER_DETAILS" | jq -r '.name')"
echo "   Instance ID: $(echo "$WORKER_DETAILS" | jq -r '.aws_instance_id')"
echo "   Status: $(echo "$WORKER_DETAILS" | jq -r '.status')"
echo "   Instance Type: $(echo "$WORKER_DETAILS" | jq -r '.instance_type')"
echo "   Created: $(echo "$WORKER_DETAILS" | jq -r '.created_at')"
