#!/usr/bin/env python
"""Script to diagnose and fix duplicate lab records in the database.

This script:
1. Connects to MongoDB
2. Identifies duplicate lab records (same worker_id + lab_id)
3. Keeps the most recently updated record
4. Removes older duplicates
5. Ensures unique index exists
"""

import asyncio
import logging
import sys
from collections import defaultdict
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from application.settings import Settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)


async def analyze_duplicates(collection):
    """Analyze duplicate lab records in the database."""
    log.info("🔍 Analyzing lab records for duplicates...")

    # Get all lab records
    cursor = collection.find({})
    records = []
    async for doc in cursor:
        records.append(doc)

    log.info(f"📊 Total lab records found: {len(records)}")

    # Group by (worker_id, lab_id)
    groups = defaultdict(list)
    for record in records:
        key = (record.get("worker_id"), record.get("lab_id"))
        groups[key].append(record)

    # Find duplicates
    duplicates = {k: v for k, v in groups.items() if len(v) > 1}

    if not duplicates:
        log.info("✅ No duplicates found!")
        return []

    log.info(f"⚠️  Found {len(duplicates)} sets of duplicate records:")
    for (worker_id, lab_id), records_list in duplicates.items():
        log.info(f"  • Worker {worker_id[:8]}... + Lab {lab_id[:8]}...: {len(records_list)} duplicates")
        for rec in records_list:
            last_synced = rec.get("last_synced_at", "unknown")
            state_version = rec.get("state_version", 0)
            log.info(f"    - ID: {rec['id'][:8]}... | Version: {state_version} | Last synced: {last_synced}")

    return duplicates


async def remove_duplicates(collection, duplicates, dry_run=True):
    """Remove duplicate lab records, keeping the most recent one."""
    if not duplicates:
        log.info("✅ No duplicates to remove")
        return

    removed_count = 0

    for (worker_id, lab_id), records_list in duplicates.items():
        # Sort by last_synced_at (most recent first), then by state_version
        sorted_records = sorted(
            records_list,
            key=lambda r: (
                r.get("last_synced_at") or "",
                r.get("state_version", 0),
            ),
            reverse=True,
        )

        # Keep the first (most recent), remove the rest
        keep_record = sorted_records[0]
        remove_records = sorted_records[1:]

        log.info(
            f"🔧 Worker {worker_id[:8]}... + Lab {lab_id[:8]}...: "
            f"Keeping ID {keep_record['id'][:8]}... (v{keep_record.get('state_version', 0)})"
        )

        for rec in remove_records:
            rec_id = rec["id"]
            if dry_run:
                log.info(f"  [DRY RUN] Would remove ID {rec_id[:8]}... (v{rec.get('state_version', 0)})")
            else:
                result = await collection.delete_one({"id": rec_id})
                if result.deleted_count > 0:
                    log.info(f"  ✅ Removed ID {rec_id[:8]}... (v{rec.get('state_version', 0)})")
                    removed_count += 1
                else:
                    log.error(f"  ❌ Failed to remove ID {rec_id[:8]}...")

    if not dry_run:
        log.info(f"✅ Removed {removed_count} duplicate records")
    else:
        log.info(f"[DRY RUN] Would remove {sum(len(v) - 1 for v in duplicates.values())} duplicate records")


async def ensure_unique_index(collection):
    """Ensure unique compound index on (worker_id, lab_id) exists."""
    log.info("🔧 Ensuring unique index on (worker_id, lab_id)...")

    try:
        # Get existing indexes
        existing_indexes = await collection.list_indexes().to_list(length=None)
        index_names = [idx["name"] for idx in existing_indexes]

        log.info(f"📊 Existing indexes: {index_names}")

        # Check if unique index exists
        has_unique_index = False
        for idx in existing_indexes:
            if "worker_id" in str(idx.get("key", {})) and "lab_id" in str(idx.get("key", {})):
                if idx.get("unique"):
                    has_unique_index = True
                    log.info(f"✅ Found existing unique index: {idx['name']}")
                else:
                    log.warning(f"⚠️  Found non-unique index: {idx['name']}")

        if not has_unique_index:
            log.info("🔧 Creating unique compound index on (worker_id, lab_id)...")
            await collection.create_index(
                [("worker_id", 1), ("lab_id", 1)],
                unique=True,
                name="unique_worker_lab",
            )
            log.info("✅ Unique index created successfully")
        else:
            log.info("✅ Unique index already exists")

    except Exception as e:
        log.error(f"❌ Failed to ensure unique index: {e}", exc_info=True)


async def main():
    """Main execution function."""
    import argparse

    parser = argparse.ArgumentParser(description="Fix duplicate lab records in MongoDB")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Actually remove duplicates (default is dry-run)",
    )
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Skip index creation/verification",
    )
    parser.add_argument(
        "--mongo-uri",
        type=str,
        help="MongoDB connection URI (overrides settings)",
    )
    args = parser.parse_args()

    dry_run = not args.fix

    if dry_run:
        log.info("🧪 Running in DRY RUN mode (use --fix to actually remove duplicates)")
    else:
        log.warning("⚠️  Running in FIX mode - will remove duplicate records!")

    # Load settings
    settings = Settings()

    # Parse MongoDB connection string
    mongo_uri = settings.connection_strings.get(
        "mongo",
        "mongodb://root:pass@mongodb:27017/?authSource=admin",  # pragma: allowlist secret
    )
    db_name = "lablet_cloud_manager"

    log.info(f"🔗 Connecting to MongoDB: {db_name}")

    # Connect to MongoDB
    client = AsyncIOMotorClient(mongo_uri)
    db = client[db_name]
    collection = db["lab_records"]

    try:
        # Step 1: Analyze duplicates
        duplicates = await analyze_duplicates(collection)

        # Step 2: Remove duplicates
        if duplicates:
            await remove_duplicates(collection, duplicates, dry_run=dry_run)

        # Step 3: Ensure unique index exists (unless skipped)
        if not args.skip_index:
            await ensure_unique_index(collection)

        log.info("✅ Script completed successfully")

    except Exception as e:
        log.error(f"❌ Script failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
