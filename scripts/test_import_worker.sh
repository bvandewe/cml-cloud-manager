#!/bin/bash
# Script to test CML Worker import functionality

set -e

# Configuration
KEYCLOAK_URL="http://localhost:8031"
API_URL="http://localhost:8030"
REALM="lablet-cloud-manager"
CLIENT_ID="lablet-cloud-manager-public"
USERNAME="${1:-admin}"
PASSWORD="${2:-admin}"
AWS_REGION="${3:-us-east-1}"
AMI_NAME="${4:-cisco-cml2.9-lablet-v0.1.7}"

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
echo "📋 Checking existing workers..."

# List existing workers
curl -s -X GET \
  "${API_URL}/api/workers/region/${AWS_REGION}/workers" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" | jq '.'

echo ""
echo "🔍 Importing CML Worker with AMI name: ${AMI_NAME}"

# Import worker by AMI name
IMPORT_RESPONSE=$(curl -s -X POST \
  "${API_URL}/api/workers/region/${AWS_REGION}/workers/import" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"ami_name\": \"${AMI_NAME}\",
    \"name\": \"imported-worker-$(date +%s)\"
  }")

echo ""
echo "📊 Import Response:"
echo "$IMPORT_RESPONSE" | jq '.'

# Check if import was successful
if echo "$IMPORT_RESPONSE" | jq -e '.id' > /dev/null 2>&1; then
  echo ""
  echo "✅ Successfully imported CML Worker!"
  WORKER_ID=$(echo "$IMPORT_RESPONSE" | jq -r '.id')
  WORKER_NAME=$(echo "$IMPORT_RESPONSE" | jq -r '.instance_name')
  INSTANCE_ID=$(echo "$IMPORT_RESPONSE" | jq -r '.aws_instance_id')
  echo "   Worker ID: ${WORKER_ID}"
  echo "   Worker Name: ${WORKER_NAME}"
  echo "   Instance ID: ${INSTANCE_ID}"

  echo ""
  echo "📋 Verifying worker appears in list..."
  curl -s -X GET \
    "${API_URL}/api/workers/region/${AWS_REGION}/workers" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" | jq '.'
else
  echo ""
  echo "❌ Failed to import worker"
  exit 1
fi
