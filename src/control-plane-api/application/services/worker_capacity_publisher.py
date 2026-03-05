"""Worker Capacity Publisher for etcd.

Publishes worker capacity data to etcd so the resource-scheduler
can read current capacity for placement decisions.

Phase 1: Worker Foundation - Capacity Tracking
Key path: /workers/{worker_id}/capacity

This service can be called directly from capacity commands
or used as an event-driven notification handler.
"""

import json
import logging
from datetime import datetime, timezone

from integration.services.etcd_client import EtcdClient

log = logging.getLogger(__name__)

# etcd key pattern for worker capacity
WORKER_CAPACITY_KEY_PATTERN = "/workers/{worker_id}/capacity"


class WorkerCapacityPublisher:
    """Publishes worker capacity snapshots to etcd.

    Provides a centralized service for syncing worker capacity data
    to etcd, enabling the resource-scheduler to read up-to-date
    capacity information for placement decisions.
    """

    def __init__(self, etcd_client: EtcdClient):
        self._etcd = etcd_client

    async def publish_capacity(
        self,
        worker_id: str,
        declared_capacity: dict | None,
        allocated_capacity: dict,
        available_capacity: dict | None,
        assigned_instance_count: int,
    ) -> bool:
        """Publish worker capacity data to etcd.

        Args:
            worker_id: ID of the CMLWorker
            declared_capacity: Total capacity from template (dict or None)
            allocated_capacity: Currently allocated capacity (dict)
            available_capacity: Remaining capacity (dict or None)
            assigned_instance_count: Number of lablet instances assigned

        Returns:
            True if published successfully, False otherwise
        """
        key = WORKER_CAPACITY_KEY_PATTERN.format(worker_id=worker_id)

        capacity_data = {
            "worker_id": worker_id,
            "declared_capacity": declared_capacity,
            "allocated_capacity": allocated_capacity,
            "available_capacity": available_capacity,
            "assigned_instance_count": assigned_instance_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            value = json.dumps(capacity_data)
            await self._etcd.put(key, value)
            log.debug(f"Published capacity for worker {worker_id}: instances={assigned_instance_count}, allocated={allocated_capacity}")
            return True

        except Exception as e:
            log.error(f"Failed to publish capacity for worker {worker_id}: {e}")
            return False

    async def remove_capacity(self, worker_id: str) -> bool:
        """Remove worker capacity data from etcd (e.g., on termination).

        Args:
            worker_id: ID of the CMLWorker

        Returns:
            True if removed successfully, False otherwise
        """
        key = WORKER_CAPACITY_KEY_PATTERN.format(worker_id=worker_id)

        try:
            await self._etcd.delete(key)
            log.info(f"Removed capacity data for worker {worker_id}")
            return True

        except Exception as e:
            log.error(f"Failed to remove capacity for worker {worker_id}: {e}")
            return False

    async def get_all_capacities(self) -> dict[str, dict]:
        """Get all worker capacity data from etcd.

        Returns:
            Dict mapping worker_id to capacity data
        """
        prefix = "/workers/"

        try:
            kvs = await self._etcd.get_prefix(prefix)
            result = {}
            for kv in kvs:
                if kv.key.endswith("/capacity"):
                    try:
                        data = json.loads(kv.value)
                        worker_id = data.get("worker_id", "")
                        if worker_id:
                            result[worker_id] = data
                    except json.JSONDecodeError:
                        log.warning(f"Invalid JSON in etcd key {kv.key}")
            return result

        except Exception as e:
            log.error(f"Failed to get worker capacities from etcd: {e}")
            return {}
