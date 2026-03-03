#!/bin/bash
# Script to check MongoDB for worker events

MONGODB_URI="mongodb://root:password123@localhost:8032"  # pragma: allowlist secret
DATABASE="lablet_cloud_manager"
COLLECTION="cml_workers"

echo "🔍 Querying MongoDB for CML Worker events..."
echo ""

# Query the worker document
docker exec lablet-cloud-manager-mongodb-1 mongosh \
  --username root \
  --password password123 \
  --authenticationDatabase admin \
  --eval "
    use lablet_cloud_manager;
    db.cml_workers.find(
      { id: '507fb3ed-5603-4c26-8ffb-37d45221f5f5' },
      { id: 1, aws_instance_id: 1, name: 1, 'state.events': 1 }
    ).pretty();
  "
