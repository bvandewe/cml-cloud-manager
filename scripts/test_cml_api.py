#!/usr/bin/env python3
"""Test script for CML API Client.

This script tests the CML API client against actual CML worker instances.
It demonstrates JWT authentication and system stats retrieval.

Usage:
    # Test with specific worker endpoint
    python scripts/test_cml_api.py --endpoint https://52.1.2.3 --username admin --password admin

    # Test with worker ID (looks up from database)
    python scripts/test_cml_api.py --worker-id 9b42b7e7-af50-4b55-ac1a-e0d9f00eefdf

    # Test all RUNNING workers
    python scripts/test_cml_api.py --test-all
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# noqa: E402 (module level imports after path modification)
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from neuroglia.serialization.json import JsonSerializer  # noqa: E402

from application.settings import app_settings  # noqa: E402
from domain.entities.cml_worker import CMLWorker  # noqa: E402
from domain.enums import CMLServiceStatus, CMLWorkerStatus  # noqa: E402
from integration.repositories.motor_cml_worker_repository import (  # noqa: E402
    MongoCMLWorkerRepository,
)
from integration.services.cml_api_client import CMLApiClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)


async def setup_repository() -> MongoCMLWorkerRepository:
    """Setup worker repository with MongoDB connection."""
    # Get MongoDB connection string
    mongo_uri = app_settings.connection_strings.get(
        "mongo",
        "mongodb://root:password123@localhost:27017/?authSource=admin",  # pragma: allowlist secret
    )

    # Create Motor client
    client = AsyncIOMotorClient(mongo_uri)

    # Create serializer
    serializer = JsonSerializer()

    # Create repository
    repository = MongoCMLWorkerRepository(
        client=client,
        database_name="lablet_cloud_manager",
        collection_name="cml_workers",
        serializer=serializer,
        entity_type=CMLWorker,
        mediator=None,  # No mediator needed for read-only test script
    )

    return repository


async def test_endpoint(endpoint: str, username: str, password: str):
    """Test CML API client against a specific endpoint.

    Args:
        endpoint: HTTPS endpoint URL
        username: CML username
        password: CML password
    """
    log.info(f"Testing CML API at: {endpoint}")
    log.info(f"Username: {username}")

    try:
        # Create client
        client = CMLApiClient(
            base_url=endpoint,
            username=username,
            password=password,
            verify_ssl=False,  # CML uses self-signed certs
            timeout=30.0,
        )

        # Test authentication
        log.info("Step 1: Testing authentication...")
        token = await client._authenticate()
        log.info(f"✅ Authentication successful! Token: {token[:50]}...")

        # Test system_stats endpoint
        log.info("\nStep 2: Testing system_stats endpoint...")
        stats = await client.get_system_stats()

        if stats:
            log.info("✅ Successfully retrieved system stats!")
            log.info("\n=== System Statistics ===")
            log.info(f"CPU: {stats.all_cpu_count} cores @ {stats.all_cpu_percent:.2f}% utilization")
            log.info(
                f"Memory: {stats.all_memory_used / (1024**3):.2f} GB used / {stats.all_memory_total / (1024**3):.2f} GB total"
            )
            log.info(
                f"Disk: {stats.all_disk_used / (1024**3):.2f} GB used / {stats.all_disk_total / (1024**3):.2f} GB total"
            )
            log.info("\n=== CML Workload ===")
            log.info(f"Allocated CPUs: {stats.allocated_cpus}")
            log.info(f"Allocated Memory: {stats.allocated_memory / 1024:.2f} MB")
            log.info(f"Total Nodes: {stats.total_nodes}")
            log.info(f"Running Nodes: {stats.running_nodes}")

            log.info("\n=== Compute Nodes ===")
            for compute_id, compute_data in stats.computes.items():
                hostname = compute_data.get("hostname", "unknown")
                is_controller = compute_data.get("is_controller", False)
                log.info(f"  {hostname} (controller={is_controller})")

            log.info(f"\n✅ All tests passed for {endpoint}")
            return True
        else:
            log.warning("⚠️  System stats returned None")
            return False

    except Exception as e:
        log.error(f"❌ Test failed: {e}", exc_info=True)
        return False


async def test_worker_by_id(worker_id: str, username: str, password: str):
    """Test CML API for a specific worker by ID.

    Args:
        worker_id: Worker UUID
        username: CML username
        password: CML password
    """
    log.info(f"Looking up worker: {worker_id}")

    repo = await setup_repository()
    worker = await repo.get_by_id_async(worker_id)

    if not worker:
        log.error(f"❌ Worker not found: {worker_id}")
        return False

    log.info(f"Found worker: {worker.state.name}")
    log.info(f"  Status: {worker.state.status.value}")
    log.info(f"  Service Status: {worker.state.service_status.value}")
    log.info(f"  HTTPS Endpoint: {worker.state.https_endpoint}")

    if not worker.state.https_endpoint:
        log.error("❌ Worker has no HTTPS endpoint configured")
        return False

    if worker.state.status != CMLWorkerStatus.RUNNING:
        log.warning(f"⚠️  Worker is not RUNNING (status: {worker.state.status.value})")
        return False

    if worker.state.service_status != CMLServiceStatus.AVAILABLE:
        log.warning(f"⚠️  Worker service is not AVAILABLE (status: {worker.state.service_status.value})")

    return await test_endpoint(worker.state.https_endpoint, username, password)


async def test_all_workers(username: str, password: str):
    """Test CML API for all RUNNING workers.

    Args:
        username: CML username
        password: CML password
    """
    log.info("Testing all RUNNING workers...")

    repo = await setup_repository()
    workers = await repo.get_all_async()

    running_workers = [w for w in workers if w.state.status == CMLWorkerStatus.RUNNING and w.state.https_endpoint]

    if not running_workers:
        log.warning("⚠️  No RUNNING workers with HTTPS endpoints found")
        return False

    log.info(f"Found {len(running_workers)} RUNNING workers to test")

    results = []
    for worker in running_workers:
        log.info(f"\n{'='*60}")
        log.info(f"Testing worker: {worker.state.name} ({worker.state.id})")
        log.info(f"{'='*60}")

        success = await test_worker_by_id(worker.state.id, username, password)
        results.append((worker.state.name, success))

    log.info(f"\n{'='*60}")
    log.info("Summary")
    log.info(f"{'='*60}")
    for name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        log.info(f"{status} - {name}")

    return all(success for _, success in results)


def main():
    parser = argparse.ArgumentParser(description="Test CML API Client")
    parser.add_argument("--endpoint", help="CML HTTPS endpoint URL (e.g., https://52.1.2.3)")
    parser.add_argument("--worker-id", help="Worker UUID to test")
    parser.add_argument("--test-all", action="store_true", help="Test all RUNNING workers")
    parser.add_argument("--username", default="admin", help="CML username (default: admin)")
    parser.add_argument("--password", default="admin", help="CML password (default: admin)")

    args = parser.parse_args()

    if args.endpoint:
        success = asyncio.run(test_endpoint(args.endpoint, args.username, args.password))
    elif args.worker_id:
        success = asyncio.run(test_worker_by_id(args.worker_id, args.username, args.password))
    elif args.test_all:
        success = asyncio.run(test_all_workers(args.username, args.password))
    else:
        parser.print_help()
        sys.exit(1)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
    main()
